"""Generate honest per-journey and per-feature reports with exact source lines."""

from __future__ import annotations

import ast
import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote


@lru_cache(maxsize=512)
def _source_nodes(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    found = []

    def collect(body, parents=()):
        for node in body:
            if isinstance(node, ast.ClassDef):
                collect(node.body, (*parents, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.append(("::".join((*parents, node.name)), node))

    collect(tree.body)
    return found


def source_section(root: Path, path: str, function: str, *, github=False):
    """Resolve line ranges from Python syntax, so edits cannot stale the links."""
    function = function.split("[", 1)[0]
    matches = [node for name, node in _source_nodes(root / path) if name == function]
    if len(matches) != 1:
        raise ValueError(f"Cannot resolve one source section for {path}::{function}")
    node = matches[0]
    start = min([node.lineno, *[d.lineno for d in node.decorator_list]])
    end = node.end_lineno
    if github:
        repository = os.environ.get("GITHUB_REPOSITORY", "SunnyLich/OpenWand")
        revision = os.environ.get("GITHUB_SHA", "main")
        target = f"https://github.com/{repository}/blob/{quote(revision, safe='')}/{quote(path)}#L{start}-L{end}"
    else:
        target = f"{(root / path).as_posix()}:{start}"
    return {"start": start, "end": end, "url": target, "description": ast.get_docstring(node) or function.replace("_", " ")}


def render(root: Path, results: list[dict], *, github=False, runtime=None):
    from scripts.user_journeys.scenarios import CASES

    by_id = {row["id"]: row for row in results}
    counts = Counter(by_id.get(case["id"], {}).get("status", "not executed") for case in CASES)
    runtime = runtime or {}
    lines = [
        "# OpenWand user journey failure detection report" if runtime.get("negative_control") else "# OpenWand user journey test report", "",
        "A pass below requires the actual app UI, supervisor, four worker processes, production SDK, and persistent stores to run together. "
        "Hosted tests substitute the external HTTP provider, credential vault, browser callbacks and desktop context. They do not verify a live provider account, successful browser sign-in, native desktop permissions, or an installed release. "
        "**Full-product acceptance is not established by this bounded suite; unresolved coverage is listed below.**", "",
        f"Build: `{runtime.get('revision', 'local working tree')}`. Runtime: `{runtime.get('platform', 'not executed')}`. "
        f"Application: `{runtime.get('kind', 'source')}`. Provider: **HTTP fixture**. Credentials: **disposable keyring backend**. Browser: **account-free callback fixture**. Desktop context: **synthetic OS input**.", "",
        f"Overall execution: **{runtime.get('execution_status', 'not verified')}**.", "",
        f"Registered journeys: **{len(CASES)}**. " + "; ".join(f"{name}: **{count}**" for name, count in sorted(counts.items())) + ".", "",
        "## Numbered whole application journeys", "",
        "| Test | What the user does and what is verified | Result | Test code section |",
        "|---|---|---|---|",
    ]
    if runtime.get("runner_error"):
        lines[10:10] = ["Runner failure: " + runtime["runner_error"].replace("\n", " "), ""]
    if runtime.get("negative_control"):
        lines[2:2] = ["This negative control deliberately returns an unrelated provider answer. The first-prompt journey is expected to fail; it is not an acceptance run.", ""]
    features = {}
    for index, case in enumerate(CASES, 1):
        row = by_id.get(case["id"], {"status": "not executed"})
        section = source_section(root, case["source_path"], case["id"], github=github)
        lines.append(f"| {index} | {case['title']} | **{row['status']}** | [Lines {section['start']}-{section['end']}]({section['url']}) |")
        case_features = case["features"]
        if case["id"] == "test_01_launch_and_open_settings" and runtime.get("kind") == "packaged":
            case_features = ["F001" if feature == "F002" else feature for feature in case_features]
        for feature in case_features:
            features.setdefault(feature, []).append((index, row["status"]))
    lines += ["", "## What each code section does", ""]
    for index, case in enumerate(CASES, 1):
        row = by_id.get(case["id"], {"status": "not executed"})
        source = (root / case["source_path"]).read_text(encoding="utf-8").splitlines()
        section = source_section(root, case["source_path"], case["id"], github=github)
        comments = [line.strip()[2:] for line in source[section["start"] - 1:section["end"]] if line.strip().startswith("# ")]
        lines += [f"### Test {index} {case['title']}", "", " ".join(comments), "", f"Result: **{row['status']}**. [Open test code, lines {section['start']}-{section['end']}]({section['url']}).", ""]
        if row.get("error"):
            lines += ["```text", row["error"].strip(), "```", ""]
        if row.get("capture_error"):
            lines += ["Evidence capture failed: " + row["capture_error"], ""]
        screenshots = set(row.get("evidence", {}).get("screenshots", []))
        screenshots.update(path for step in row.get("steps", []) for path in step.get("observation", {}).get("screenshots", []))
        for path in sorted(screenshots):
            lines.append(f"[Window screenshot]({path})")
        previews = {event["screenshot"] for step in row.get("steps", []) for event in step.get("observation", {}).get("extended", {}).get("dialog_events", []) if event.get("screenshot")}
        for path in sorted(previews):
            lines.append(f"[Approval preview before the user's choice]({path})")
        if row.get("evidence", {}).get("screenshots"):
            lines.append("")
    lines += [
        "## Shared code sections", "",
        "| Section | Responsibility | Source |", "|---|---|---|",
    ]
    for path, function, purpose in (
        ("scripts/user_journeys/ui_driver.py", "dispatch", "Find actual widgets, deliver user input, and read visible state"),
        ("scripts/user_journeys/dialog_driver.py", "queue_dialogs", "Type and click real dialogs and live file approvals, capturing choices and pre-write evidence"),
        ("scripts/user_journeys/dialog_driver.py", "watch_unexpected_dialogs", "Cancel unplanned modal dialogs safely and fail their story instead of hanging the remaining suite"),
        ("scripts/user_journeys/basic_scenarios.py", "model_test", "Require a visible Settings test result and a real authenticated HTTP probe"),
        ("scripts/user_journeys/addon_scenarios.py", "enabled", "Wait for the refreshed user-visible tool listing after an addon toggle"),
        ("scripts/user_journeys/agent_driver.py", "act", "Use actual agent forms, buttons, history rows and tabs"),
        ("scripts/user_journeys/workspace_driver.py", "act", "Use Shared Workspace's real file tree, context menus, keyboard shortcuts and editor"),
        ("scripts/user_journeys/desktop_boundary.py", "handlers", "Explicit synthetic OS input, protecting personal desktop context"),
        ("scripts/user_journeys/oauth_browser.py", "main", "External browser fixture sends declined or invalid callbacks; never issues an account token"),
        ("scripts/user_journeys/extended_scenarios.py", "bubble_reply", "Require a different response identity, completed state and actual visible bubble text"),
        ("scripts/user_journeys/extended_scenarios.py", "tool_outcomes", "Read real tool results after the current user request to verify rejected file operations"),
        ("scripts/user_journeys/scenarios.py", "App::ui", "Pass input through real supervisor-to-UI IPC and record observations"),
        ("scripts/user_journeys/scenarios.py", "App::reply", "Require a visible completed response and usable controls"),
        ("scripts/user_journeys/scenarios.py", "App::request", "Check the independent provider's actual HTTP request"),
        ("scripts/user_journeys/provider_server.py", "ProviderServer::__init__", "Explicit external provider fixture and independent network evidence"),
        ("scripts/user_journeys/__main__.py", "run", "Fresh state, real app launches, restart, worker cleanup and overall failure status"),
        ("scripts/user_journeys/report.py", "validate_execution", "Reject missing, skipped, repeated or evidence-free required journeys"),
    ):
        section = source_section(root, path, function, github=github)
        lines.append(f"| `{function}` | {purpose} | [{path}: {section['start']}-{section['end']}]({section['url']}) |")
    lines += ["",
        "## All inventoried product functions", "",
        "This table prevents feature counts from being mistaken for whole-app coverage. "
        "Legacy tests are linked for review; their old acceptance labels are not counted as a passed whole-app journey. "
        "A linked test that has not run in this execution remains unverified here.", "",
        "| Function | User capability | Whole-app evidence in this run | Existing test code to inspect |",
        "|---|---|---|---|",
    ]
    acceptance = json.loads((root / "tests/workflows/feature_acceptance.json").read_text(encoding="utf-8"))
    covered = 0
    for record in acceptance["records"]:
        mapped = features.get(record["function_id"], [])
        if any(status == "passed" for _, status in mapped):
            covered += 1
        status = "; ".join(f"Test {i}: {s}" for i, s in mapped) or "**No whole-app journey implemented**"
        links = []
        for node in record.get("test_node_ids", []):
            path, function = node.split("::", 1)
            try:
                section = source_section(root, path, function, github=github)
                links.append(f"[{Path(path).name}: {section['start']}-{section['end']}]({section['url']})")
            except (OSError, ValueError, SyntaxError):
                links.append(f"Unresolved source reference: `{node}`")
        name = record["function"].replace("|", "\\|")
        lines.append(f"| {record['function_id']} | {name} | {status} | {'; '.join(links) or 'None'} |")
    lines += ["", f"Whole-app execution evidence touches **{covered}/{len(acceptance['records'])}** inventoried functions in this run. "
              "A linked journey covers only its stated actions and states, not every variant of the inventory function. "
              "Unimplemented, blocked and unexecuted items are not passes.", "",
              "## Required external acceptance", "",
              "| Scope | Required evidence | Status in this report |", "|---|---|---|",
              "| ChatGPT browser sign-in | Actual browser approval, saved session, prompt, restart, sign-out | Unverified; HTTP fixture is not OAuth |",
              "| Live cloud and local providers | Each configured provider receives and answers a real UI prompt | Unverified by hosted HTTP fixture |",
              "| Voice and desktop integration | Microphone, audio playback, shortcuts, capture and paste on an isolated desktop | Unverified by this suite |",
              "| Installed release lifecycle | Actual installer, update, restart, keep-data and remove-data uninstall | Unverified by source run |",
              "| Remaining feature journeys | Complete user-driven paths for every uncovered inventory row above | Open coverage gaps |", ""]
    workspace_cases = [str(index) for index, case in enumerate(CASES, 1) if case["phase"] == "workspace"]
    lines += ["The older inventory also predates some app-action and Shared Workspace features. "
              "Shared Workspace journeys in this report are tests " + ", ".join(workspace_cases) + ". "
              "Those cover the specifically described paths; change-review conflicts, other app actions and unimplemented variants remain work to do. "
              "See coverage-checklist.md for every inventoried capability and remaining work.", ""]
    return "\n".join(lines)


def load_results(output: Path):
    from scripts.user_journeys.scenarios import PHASES

    results = []
    for name in PHASES:
        file = output / f"{name}-results.json"
        if file.exists():
            results.extend(json.loads(file.read_text(encoding="utf-8")))
    return results


def write_report(root: Path, output: Path, *, runtime=None):
    results = load_results(output)
    report = render(root, results, github=bool(os.environ.get("GITHUB_ACTIONS")), runtime=runtime)
    (output / "report.md").write_text(report, encoding="utf-8")
    from scripts.user_journeys.coverage_plan import render as render_checklist
    (output / "coverage-checklist.md").write_text(render_checklist(root), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and not (runtime or {}).get("negative_control"):
        # Keep the summary small; the downloadable report contains all 472 rows.
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(report.split("## What each code section does")[0])
            stream.write("\nDownload the user-journeys artifact for screenshots, exact source links, all product functions and coverage gaps.\n")
    return results


def validate_execution(results, *, output: Path | None = None):
    """Missing, repeated, skipped or blocked required journeys cannot be green."""
    from collections import Counter

    from scripts.user_journeys.scenarios import CASES

    expected = {case["id"] for case in CASES}
    counts = Counter(row["id"] for row in results)
    errors = [f"Missing journey: {name}" for name in sorted(expected - counts.keys())]
    errors += [f"Unexpected journey: {name}" for name in sorted(counts.keys() - expected)]
    errors += [f"Repeated journey: {name}" for name, count in counts.items() if count != 1]
    for row in results:
        if row.get("status") != "passed":
            errors.append(f"Journey {row['id']}: {row.get('status', 'no result')}")
        elif not row.get("steps") or not row.get("evidence", {}).get("screenshots"):
            errors.append(f"Journey {row['id']} has no input/observation or screenshot evidence")
        elif output is not None:
            for name in row["evidence"]["screenshots"]:
                file = (output / name).resolve()
                if not file.is_relative_to(output.resolve()) or not file.is_file() or not file.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    errors.append(f"Journey {row['id']} has missing or invalid screenshot evidence")
    return errors
