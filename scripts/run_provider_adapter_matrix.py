"""Run adapter tests in isolation, optionally prompting for a temporary API key.

Default is offline. Live mode never saves the key or reads OpenWand's keychain.
It cannot enforce provider billing: only use a verified non-billable/free key.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ("google", "openai", "anthropic", "openai_responses")
KEY_VARIABLES = {"google": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai_responses": "OPENAI_API_KEY"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Opt in to real provider API requests (default: offline).")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model", help="Explicit API model ID; there is no default model.")
    parser.add_argument("--free-tier-confirmed", action="store_true", help="You verified this key cannot incur any charges; request limits are not a monetary cap.")
    parser.add_argument("--scenario", help="Optional scenario ID, e.g. no_tools or dependent_rounds.")
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "provider-adapters")
    args = parser.parse_args(argv)
    if args.live and (not args.provider or not args.model or not args.free_tier_confirmed):
        parser.error("Live mode requires --provider, --model, and --free-tier-confirmed.")
    if not args.live and (args.provider or args.model or args.free_tier_confirmed or args.scenario):
        parser.error("Provider/model/scenario options require --live.")
    # A non-TTY getpass fallback could echo credentials; refuse it before asking.
    if args.live and not sys.stdin.isatty():
        parser.error("Run live mode in your own interactive terminal so the API key can be entered without echo.")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    from support.provider_adapter_matrix import SCENARIOS

    if args.scenario and args.scenario not in {scenario.id for scenario in SCENARIOS}:
        parser.error("Unknown scenario. Choose: " + ", ".join(scenario.id for scenario in SCENARIOS))
    key = ""
    if args.live:
        cases = 1 if args.scenario else len(SCENARIOS)
        print(f"Live {args.provider}/{args.model}: at most {cases * 4} requests, 768 output tokens per request, SDK retries disabled.")
        print("Only proceed with a verified non-billable key. This runner cannot disable billing or enforce a dollar cap.")
        key = getpass.getpass(f"Enter test-only {KEY_VARIABLES[args.provider]} (hidden, not saved): ").strip()
        if not key:
            parser.error("An API key is required; none was provided.")
    temp_root = ROOT / ".tmp" / "provider-adapters"
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="run-", dir=temp_root) as temp, ExitStack() as stack:
        clean_env = {
            "OPENWAND_SETTINGS_ENV_PATH": str(Path(temp) / "test.env"),
            "OPENWAND_USER_DATA_DIR": str(Path(temp) / "user-data"),
            "OPENWAND_DATA_ROOT": str(Path(temp) / "data"),
            "OPENWAND_ADAPTER_REPORT_DIR": str(args.report_dir.resolve()),
            "OPENWAND_RUN_PROVIDER_ADAPTER_TESTS": "1" if args.live else "0",
            "OPENWAND_ADDONS_DIR": str(Path(temp) / "addons"),
        }
        if args.live:
            clean_env.update({
                "OPENWAND_ADAPTER_FREE_TIER_CONFIRMED": "1",
                "OPENWAND_ADAPTER_PROVIDERS": args.provider,
                f"OPENWAND_ADAPTER_{args.provider.upper()}_MODEL": args.model,
                KEY_VARIABLES[args.provider]: key,
            })
        stack.enter_context(patch.dict(os.environ, clean_env))
        from core import secret_store

        # Apply before pytest/session hooks import config, even when PySide6 is installed.
        stack.enter_context(patch.object(secret_store, "get_secret", return_value=""))
        stack.enter_context(patch.object(secret_store, "refresh_cache"))
        if not args.live:
            def no_network(*_args, **_kwargs):
                raise AssertionError("Offline provider tests attempted network access")

            for target in ("socket.create_connection", "socket.socket.connect", "socket.socket.connect_ex"):
                stack.enter_context(patch(target, no_network))
        import pytest

        os.chdir(ROOT)
        args.report_dir.mkdir(parents=True, exist_ok=True)
        pytest_args = ["-q", "-ra", "--tb=short", f"--junitxml={args.report_dir.resolve() / ('live.xml' if args.live else 'offline.xml')}"]
        if args.live:
            selection = args.provider + (f" and {args.scenario}" if args.scenario else "")
            pytest_args += ["tests/test_provider_adapter_matrix.py", "-k", selection]
        else:
            pytest_args += [
                "tests/test_provider_adapter_protocol.py",
                "tests/test_provider_adapter_harness.py",
                "tests/test_claude_credit_runner.py",
                "tests/test_provider_adapter_matrix.py",
                "tests/integration/provider_adapters",
                "tests/test_gemini_provider_regressions.py",
                "tests/test_openai_provider_adapter.py",
            ]
        return int(pytest.main(pytest_args))


if __name__ == "__main__":
    raise SystemExit(main())
