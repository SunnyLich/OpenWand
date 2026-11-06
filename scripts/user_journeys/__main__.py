"""Run user journeys through independent app launches and retain an honest report."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.run_launcher_smoke import (
    _packaged_executable,
    _process_identity_alive,
    _source_command,
    _stop_process_tree,
    _validate_ready,
)
from scripts.user_journeys.provider_server import ProviderServer
from scripts.user_journeys.report import load_results, validate_execution, write_report

ROOT = Path(__file__).resolve().parents[2]


def _source_fingerprint():
    """Tie results to the application, fixtures and workflows actually tested."""
    result = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--",
                             "core", "runtime", "ui", "addons", "config.py", "scripts/user_journeys", "packaging", ".github/workflows"],
                            cwd=ROOT, capture_output=True, check=True)
    digest = hashlib.sha256()
    for name in sorted(set(result.stdout.decode("utf-8").split("\0")) - {""}):
        file = ROOT / name
        digest.update(name.encode("utf-8"))
        digest.update(hashlib.sha256(file.read_bytes()).digest() if file.is_file() else b"missing")
    return digest.hexdigest()


def run(output: Path, *, timeout=300, executable=None, break_response=False, debug_phase=None, state_from=None, debug_start=None):
    if debug_start and not debug_phase:
        raise ValueError("Starting partway is permitted only in a debug phase")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = output / "state"
    # Refuse to seed over an earlier user's journey. A separate report directory
    # is needed for every run, and the second launch alone reuses the first state.
    if state.exists():
        raise RuntimeError(f"Use a fresh report directory; state already exists: {state}")
    if state_from:
        state_from = state_from.resolve()
        if not (state_from / ".user-journey-state").is_file() or debug_phase is None:
            raise RuntimeError("State reuse is limited to explicitly selected debug phases and marked acceptance state")
        shutil.copytree(state_from, state)
    else:
        state.mkdir()
        (state / ".user-journey-state").touch()
    settings = state / "config" / ".env"
    settings.parent.mkdir(exist_ok=True)
    if not state_from:
        settings.write_text("\n".join([
        "OPENWAND_ONBOARDING_COMPLETE=False", "START_ON_LOGIN=False", "APP_LANGUAGE=en",
        "CHAT_EXECUTION_MODE=openwand", "CHAT_CONVERSATION_OWNER=openwand", "TTS_PROVIDER=none",
        "TTS_SPEAK_REPLIES=False", "MEMORY_AUTO_CONSOLIDATE=False", "PRIVACY_MODE=off",
        "CHAT_AUTO_ELABORATE=False", "LLM_PROVIDER=custom", "LLM_MODEL=journey-model",
        "ICON_AUTO_HIDE=False", "",
        ]), encoding="utf-8")
    runtime = {"platform": platform.platform(), "kind": "packaged" if executable else "source",
               "revision": os.environ.get("GITHUB_SHA", "local working tree"), "negative_control": break_response,
               "debug_phase": debug_phase}
    source = ROOT / "scripts/user_journeys/scenarios.py"
    runtime["scenario_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    runtime["source_hashes"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "scripts/user_journeys").glob("*.py")}
    runtime["checkout_sha256"] = _source_fingerprint()
    status = 0
    try:
        with ProviderServer(output / "provider-requests.json", break_response=break_response) as provider:
            from scripts.user_journeys.scenarios import PHASES
            for phase in ((debug_phase,) if debug_phase else PHASES):
                env = os.environ.copy()
                env["OPENWAND_E2E_DEBUG_START"] = debug_start or ""
                # Inheriting offline mode would quietly bypass the path under test.
                env.pop("OPENWAND_BRAIN_FAKE_LLM", None)
                for key in list(env):
                    if key.endswith("_API_KEY") or key.endswith("_API_TOKEN"):
                        env.pop(key)
                ready = output / f"{phase}-ready.json"
                env.update({
                    "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1", "PYTHONPATH": str(ROOT),
                    "OPENWAND_LAUNCH_PYTHON": sys.executable,
                    "OPENWAND_LAUNCH_SMOKE_DISABLE_AUTOSTART_SYNC": "1",
                    "OPENWAND_LAUNCH_SMOKE_EXIT_AFTER_READY": "1",
                    "OPENWAND_LAUNCH_SMOKE_READY_FILE": str(ready),
                    "OPENWAND_SETTINGS_ENV_PATH": str(settings),
                    "OPENWAND_DATA_ROOT": str(state / "data"), "OPENWAND_USER_DATA_DIR": str(state / "user-data"),
                    "OPENWAND_ADDONS_DIR": str(state / "addons"), "OPENWAND_MACOS_SAFE_MODE": "1",
                    # Exercise SDK tools/streaming against the local HTTP fixture;
                    # keep native audio and background-process safeguards enabled.
                    "OPENWAND_MACOS_ENABLE_OPENAI_TOOLS": "1",
                    "OPENWAND_MACOS_OPENAI_COMPAT_STREAMING": "1",
                    "OPENWAND_USER_JOURNEYS": "1", "OPENWAND_E2E_PHASE": phase,
                    "OPENWAND_E2E_STATE": str(state), "OPENWAND_E2E_OUTPUT": str(output),
                    "OPENWAND_E2E_PROVIDER_URL": provider.url,
                    "OPENWAND_SECRET_STATUS_PATH": str(state / "secret-status.json"),
                    "PYTHON_KEYRING_BACKEND": "scripts.user_journeys.keyring_backend.DisposableKeyring",
                    "CUSTOM_BASE_URL": provider.url,
                    "OPENWAND_RUNTIME_LOG_MODE": "debug",
                    "BROWSER": shlex.join([Path(sys.executable).as_posix(), "-m", "scripts.user_journeys.oauth_browser", "%s"]) + " &",
                })
                # Offscreen is an explicit hosted-GUI limitation; an isolated
                # desktop runner can supply its actual Qt platform instead.
                env.setdefault("QT_QPA_PLATFORM", "offscreen")
                command = [str(executable)] if executable else _source_command(ROOT)
                with (output / f"{phase}-process.log").open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
                    try:
                        code = process.wait(timeout=timeout)
                    except subprocess.TimeoutExpired:
                        _stop_process_tree(process)
                        process.wait(timeout=15)
                        raise RuntimeError(f"{phase} user journeys timed out after {timeout}s") from None
                if code or not ready.exists():
                    raise RuntimeError(f"{phase} app exited {code}; see {output / (phase + '-process.log')}")
                payload = json.loads(ready.read_text(encoding="utf-8"))
                identities = _validate_ready(payload, frozen=bool(executable))
                survivors = [name for name, (pid, created) in identities.items() if _process_identity_alive(pid, created)]
                if survivors:
                    raise RuntimeError(f"Managed workers survived shutdown: {survivors}")
                if not payload.get("user_journeys"):
                    raise RuntimeError("Application did not execute user journeys; refusing a startup-only pass")
            (output / "provider-requests.json").write_text(json.dumps(provider.requests, indent=2), encoding="utf-8")
            assert any("E2E_FIRST_PROMPT" in json.dumps(r) for r in provider.requests), "The real SDK never reached the provider"
            assert any("E2E_AFTER_PROCESS_RESTART" in json.dumps(r) for r in provider.requests), "Restarted app did not contact the provider"
            assert hashlib.sha256(source.read_bytes()).hexdigest() == runtime["scenario_sha256"], "Scenario code changed during execution; rerun before trusting source links"
            assert all(hashlib.sha256((source.parent / name).read_bytes()).hexdigest() == digest for name, digest in runtime["source_hashes"].items()), "Acceptance code changed during execution; rerun before trusting source links"
            assert _source_fingerprint() == runtime["checkout_sha256"], "Application or workflow code changed during execution; rerun before trusting this report"
    except Exception as error:
        runtime["runner_error"] = str(error)
        (output / "runner-error.txt").write_text(str(error), encoding="utf-8")
        print(str(error), file=sys.stderr)
        status = 1
    finally:
        results = load_results(output)
        errors = validate_execution(results, output=output)
        if errors:
            (output / "incomplete-execution.txt").write_text("\n".join(errors), encoding="utf-8")
            status = 1
        runtime["execution_status"] = "failed" if status else "passed (registered journeys only)"
        write_report(ROOT, output, runtime=runtime)
        (output / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
    print(f"User journey report: {output / 'report.md'}")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--packaged", action="store_true", help="Exercise the newly built platform executable")
    parser.add_argument("--prove-failure-detection", action="store_true", help="Require the real prompt journey to fail when the HTTP provider returns an unrelated answer")
    parser.add_argument("--debug-phase", choices=("basics", "addons", "agents", "workspace", "extended"), help="Debug one phase; missing full-suite results still prevent an acceptance pass")
    parser.add_argument("--debug-start", help="Debug from this test ID after reconnecting the disposable provider; never an acceptance run")
    parser.add_argument("--state-from", type=Path, help="Copy an earlier marked test state for a debug phase only")
    args = parser.parse_args()
    status = run(args.output, timeout=args.timeout, executable=args.executable or (_packaged_executable(ROOT) if args.packaged else None), break_response=args.prove_failure_detection, debug_phase=args.debug_phase, state_from=args.state_from, debug_start=args.debug_start)
    if args.prove_failure_detection:
        results = load_results(args.output)
        failure = next((row for row in results if row["id"] == "test_setup_04_first_prompt"), {})
        evidence = args.output / "provider-requests.json"
        requests = json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else []
        # The canary passes only if the expected visible-response assertion
        # failed after the real network call. An unrelated startup failure does
        # not count as proof that the prompt test can detect a broken result.
        detected = (status != 0 and failure.get("status") == "failed"
                    and "Timed out waiting for a visible completed provider response" in failure.get("error", "")
                    and any(row.get("authenticated") and row.get("response_variant") == "unrelated"
                            and row.get("response_finished_monotonic_ns") for row in requests))
        print("Failure-detection canary: " + ("passed" if detected else "FAILED"))
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
                stream.write("\nFailure-detection negative control: **" + ("passed" if detected else "FAILED") + "**. The intentionally wrong provider response must fail the first-prompt assertion.\n")
        return 0 if detected else 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
