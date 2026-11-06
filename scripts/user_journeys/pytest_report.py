"""Explain each executed existing test and link its exact current source range.

This supplements the whole-app report. A passing component or UI test is still
labelled as existing-suite evidence, never silently promoted to live E2E.
"""

from __future__ import annotations

import argparse
import html
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts.user_journeys.report import source_section


def render_pytest_report(root: Path, directory: Path):
    paths = sorted((root / "tests").rglob("test_*.py"))
    modules = {p.relative_to(root).with_suffix("").as_posix().replace("/", "."): p.relative_to(root).as_posix() for p in paths}
    lines = ["# Existing test suite execution report", "",
             "Each row describes an executed test and links its exact source section. "
             "These results include internal, UI and component workflows; they do not by themselves establish a complete user journey.", "",
             "| Test | What it tests | Result | Code section |", "|---|---|---|---|"]
    index = 0
    problems = []
    for file in sorted(directory.glob("*.xml")):
        try:
            suite = ET.parse(file).getroot()
        except ET.ParseError as error:
            problems.append(f"Invalid results file {file.name}: {error}")
            continue
        for case in suite.iter("testcase"):
            index += 1
            name = case.attrib.get("name", "")
            classname = case.attrib.get("classname", "")
            matches = [module for module in modules if classname == module or classname.startswith(module + ".")]
            result = "failed" if case.find("failure") is not None else "error" if case.find("error") is not None else "skipped" if case.find("skipped") is not None else "passed"
            link = "Unresolved source reference"
            purpose = name
            if matches:
                path = modules[max(matches, key=len)]
                class_name = classname[len(max(matches, key=len)):].lstrip(".").replace(".", "::")
                function = "::".join(part for part in (class_name, name) if part)
                try:
                    section = source_section(root, path, function, github=bool(os.environ.get("GITHUB_ACTIONS")))
                    link = f"[{path}: {section['start']}-{section['end']}]({section['url']})"
                    purpose = section["description"].splitlines()[0]
                except (OSError, SyntaxError, ValueError) as error:
                    problems.append(str(error))
            else:
                problems.append(f"No source file found for {classname}::{name}")
            purpose = html.escape(purpose).replace("|", "\\|")
            lines.append(f"| {index}. `{name.replace('|', ' ')}` | {purpose} | **{result}** | {link} |")
    if not index:
        problems.append("No test execution evidence was produced; this is not a passing report.")
    lines += ["", f"Executed result rows: **{index}**.", ""]
    if problems:
        lines += ["## Missing or invalid evidence", "", *[f"- {problem}" for problem in problems], ""]
    return "\n".join(lines), problems


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    report, problems = render_pytest_report(root, args.results)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
