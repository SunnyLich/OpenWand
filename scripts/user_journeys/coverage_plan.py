"""Keep the complete product inventory visible while expanding user journeys.

Written code is not execution evidence. This checklist says which user paths
exist, which still need writing, and which need an external acceptance environment.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from scripts.user_journeys.report import source_section
from scripts.user_journeys.scenarios import CASES


def inventory_groups(root):
    """Associate each of the 472 ordered entries with its inventory heading."""
    groups = []
    heading = None
    for line in (root / "docs/APP_FUNCTION_INVENTORY.md").read_text(encoding="utf-8").splitlines():
        if re.match(r"^## \d+\.", line):
            heading = line[3:]
        elif line.startswith("## "):
            heading = None
        elif heading and line.startswith("- [ ] "):
            groups.append(heading)
    return groups


def render(root):
    """Produce a checklist for every entry, never a blanket acceptance label."""
    records = json.loads((root / "tests/workflows/feature_acceptance.json").read_text(encoding="utf-8"))["records"]
    groups = inventory_groups(root)
    github = bool(os.environ.get("GITHUB_ACTIONS"))

    def file_link(path):
        if github:
            return f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'SunnyLich/OpenWand')}/blob/{os.environ.get('GITHUB_SHA', 'main')}/{path}"
        return (root / path).as_posix()
    assert len(groups) == len(records), "The checklist must include every inventoried function"
    mapped = defaultdict(list)
    for case in CASES:
        for feature in case["features"]:
            mapped[feature].append(case)
        if case["id"] == "test_01_launch_and_open_settings":
            # The same UI journey is run against a freshly built executable by
            # the build workflow; that mode is not a source-launch pass.
            mapped["F001"].append(case)
    lines = ["# Complete user journey coverage checklist", "",
             "This is the implementation work list, starting with ordinary UI actions. **Written does not mean passed or fully covered.** "
             "The execution report separately records what actually ran and which states it verified. "
             "Every missing entry below remains work to do; component-test acceptance labels do not close it.", "",
             "## Order of work", "",
             "1. Basic inputs, keyboard controls, drafts, attachments, history, model test buttons and non-destructive settings choices.",
             "2. Conversation branching/rewinding, context controls, shortcuts, appearance, privacy, memory and local file permissions.",
             "3. Add-on installation/use/removal, MCP, agent tasks, workspace review/apply/reject, failures and recovery.",
             "4. Live account sign-in and provider protocols, physical desktop/voice, installed-release lifecycle and OS-specific behavior. "
             "Write these journeys too; execute them only in an appropriate, provisioned environment.", "",
             f"Registered journeys: **{len(CASES)}**. Inventory entries: **{len(records)}**. "
             f"Entries with at least one specifically mapped path: **{sum(bool(mapped[r['function_id']]) for r in records)}**. "
             "A mapped path is not proof of every variant of that capability.", ""]
    previous = None
    for record, group in zip(records, groups, strict=True):
        if group != previous:
            lines += [f"## {group}", "", "| Capability | User journey implementation |", "|---|---|"]
            previous = group
        cases = mapped[record["function_id"]]
        links = []
        for case in cases:
            section = source_section(root, case["source_path"], case["id"], github=github)
            links.append(f"[{case['title']} (lines {section['start']}-{section['end']})]({section['url']})")
        status = "Written path: " + "; ".join(links) if links else "**TODO: write the user journey**"
        name = record["function"].replace("|", "\\|")
        lines.append(f"| {record['function_id']}: {name} | {status} |")
    lines += ["", "## Product surfaces newer than the older inventory", "",
              "These also need complete journeys; the 472-entry inventory is not the end of the task.", "",
              "| Surface | User journeys still needed | Product source |", "|---|---|---|",
              "| Shared Workspace | Written paths below cover opening, permission refusal, create/edit/rename/trash, empty task validation, reconnect and stop. "
              "Remaining: agent change review, apply/reject, stale/conflicting changes, richer previews and task recovery | "
              f"[Workspace window]({file_link('ui/virtual_workspace_window.py')}), [changes]({file_link('core/workspace_changes.py')}) |",
              "| App actions | Discover an available app action, review its plan, approve/decline, execute, verify the target application's result, recover from failure | "
              f"[Runtime routing]({file_link('runtime/supervisor/flows.py')}) |", "",
              "The external provider/browser/desktop substitutes are named in each execution report. "
              "Successful real sign-in, live service compatibility, native permissions and release installation require additional evidence.", ""]
    lines += ["## Written Shared Workspace paths", ""]
    for case in CASES:
        if case["phase"] == "workspace":
            section = source_section(root, case["source_path"], case["id"], github=github)
            lines.append(f"- [{case['title']} (lines {section['start']}-{section['end']})]({section['url']})")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/USER_JOURNEY_COVERAGE.md"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(root), encoding="utf-8")
    print(f"Full user-journey checklist: {args.output.resolve()}")


if __name__ == "__main__":
    main()
