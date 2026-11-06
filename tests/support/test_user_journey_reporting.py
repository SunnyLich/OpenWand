"""Ensure the user-journey gate cannot hide missing runs or invent code links."""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.user_journeys.pytest_report import render_pytest_report
from scripts.user_journeys.report import source_section, validate_execution
from scripts.user_journeys.scenarios import CASES


@pytest.mark.parametrize("constructor", ["helper", "instance"])
def test_dialog_title_tracking_keeps_real_qt_choice_when_native_title_is_empty(monkeypatch, constructor):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox

    from scripts.user_journeys.dialog_driver import dialog_title, track_message_box_titles

    app = QApplication.instance() or QApplication([])
    host = SimpleNamespace()
    # Restore the actual Qt helpers after this one test's instrumentation.
    original_set_title = QMessageBox.setWindowTitle
    for name in ("question", "information", "warning", "critical", "setWindowTitle"):
        monkeypatch.setattr(QMessageBox, name, getattr(QMessageBox, name))
    track_message_box_titles(host)
    observed = []
    errors = []

    def choose_no():
        modal = QApplication.activeModalWidget()
        try:
            assert isinstance(modal, QMessageBox)
            original_set_title(modal, "")  # Native title loss must not change the requested title.
            observed.append(dialog_title(host, modal))
            QTest.mouseClick(modal.button(QMessageBox.StandardButton.No), Qt.MouseButton.LeftButton)
        except Exception as error:
            errors.append(str(error))
            if isinstance(modal, QMessageBox):
                modal.reject()

    QTimer.singleShot(0, choose_no)
    if constructor == "helper":
        choice = QMessageBox.question(None, "Review Addon Access", "Allow access?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    else:
        dialog = QMessageBox()
        dialog.setWindowTitle("Review Addon Access")
        dialog.setText("Allow access?")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        choice = dialog.exec()
    assert not errors
    assert observed == ["Review Addon Access"]
    assert choice == QMessageBox.StandardButton.No
    assert host._journey_message_titles == []
    app.processEvents()


def complete_results():
    """A compact valid report fixture; this does not run or certify the app."""
    return [{"id": case["id"], "status": "passed", "steps": [{"action": "snapshot"}], "evidence": {"screenshots": ["window.png"]}} for case in CASES]


def test_workspace_open_driver_activates_a_real_file_tree_by_double_click():
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    from scripts.user_journeys.workspace_driver import act
    from ui.workspace_file_tree import WorkspaceFileTree

    app = QApplication.instance() or QApplication([])
    class WorkspaceWindowFixture(QWidget):
        def __init__(self):
            super().__init__()
            self._desktop = SimpleNamespace(_icons=WorkspaceFileTree(self))
            QVBoxLayout(self).addWidget(self._desktop._icons)

    window = WorkspaceWindowFixture()
    tree = window._desktop._icons
    host = SimpleNamespace(_virtual_workspace_window=window)
    activated = []
    tree.file_activated.connect(activated.append)
    tree.set_entries([{"path": "notes/document.txt", "kind": "file"}])
    window.resize(500, 400)
    window.show()
    app.processEvents()
    try:
        act(host, "workspace_open", {"path": "notes/document.txt"}, click=None, type_text=None, button=None)
        app.processEvents()
        assert activated == ["notes/document.txt"]
    finally:
        window.close()
        app.processEvents()


def test_missing_journey_fails_even_when_every_emitted_result_passes():
    # Removing one result must fail the gate, not quietly reduce the denominator.
    results = complete_results()
    omitted = results.pop()
    assert f"Missing journey: {omitted['id']}" in validate_execution(results)


@pytest.mark.parametrize("status", ["skipped", "blocked", "failed", "running"])
def test_required_journey_must_have_actually_passed(status):
    # A prerequisite failure, missing account, or timeout cannot turn green.
    results = complete_results()
    results[0]["status"] = status
    assert validate_execution(results)


def test_repeated_and_evidence_free_results_are_rejected():
    # Test evidence must exist, and repeating one case cannot replace another.
    results = complete_results()
    assert not validate_execution(results)
    repeated = [*results, copy.deepcopy(results[0])]
    assert any("Repeated" in error for error in validate_execution(repeated))
    results[0]["evidence"] = {}
    assert any("no input/observation or screenshot" in error for error in validate_execution(results))


def test_source_links_use_actual_decorated_function_and_class_lines(tmp_path, monkeypatch):
    # Two classes may use the same method name. Resolve the correct class and
    # include the decorator, rather than returning an unrelated matching name.
    code = "class First:\n    @mark\n    def test_prompt(self):\n        pass\n\nclass Second:\n    def test_prompt(self):\n        pass\n"
    (tmp_path / "cases.py").write_text(code, encoding="utf-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/product")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    first = source_section(tmp_path, "cases.py", "First::test_prompt[value]", github=True)
    second = source_section(tmp_path, "cases.py", "Second::test_prompt", github=True)
    assert (first["start"], first["end"]) == (2, 4)
    assert first["url"] == "https://github.com/example/product/blob/abc123/cases.py#L2-L4"
    assert (second["start"], second["end"]) == (7, 8)


def test_pytest_report_preserves_failure_skip_and_source_sections(tmp_path):
    # Read real JUnit structure and retain failure/skip status in the human report.
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_prompt.py").write_text('def test_prompt():\n    """Type a prompt and inspect the visible answer."""\n    assert True\n', encoding="utf-8")
    results = tmp_path / "results"
    results.mkdir()
    root = ET.Element("testsuite")
    for status in ("passed", "failure", "skipped"):
        case = ET.SubElement(root, "testcase", classname="tests.test_prompt", name=f"test_prompt[{status}]")
        if status != "passed":
            ET.SubElement(case, status)
    ET.ElementTree(root).write(results / "results.xml")
    report, problems = render_pytest_report(tmp_path, results)
    assert problems == []
    assert "Type a prompt and inspect the visible answer." in report
    assert "**failed**" in report and "**skipped**" in report and "**passed**" in report
    assert "test_prompt.py: 1-3" in report


def test_no_execution_evidence_cannot_produce_a_successful_report(tmp_path):
    # An empty artifact directory must not be described as an all-passing suite.
    _report, problems = render_pytest_report(tmp_path, tmp_path)
    assert any("No test execution evidence" in problem for problem in problems)


def test_all_numbered_journeys_have_explanatory_comments_and_resolvable_code():
    # Keep the source readable and every numbered report link navigable.
    root = Path(__file__).resolve().parents[2]
    for case in CASES:
        source = root / case["source_path"]
        lines = source.read_text(encoding="utf-8").splitlines()
        section = source_section(root, case["source_path"], case["id"])
        assert any(line.strip().startswith("# ") for line in lines[section["start"] - 1:section["end"]])


def test_coverage_checklist_retains_every_inventory_entry_and_explicit_gaps():
    # Adding journeys must not shrink the product scope or make an unwritten
    # capability disappear from the work list.
    import json

    from scripts.user_journeys.coverage_plan import render

    root = Path(__file__).resolve().parents[2]
    records = json.loads((root / "tests/workflows/feature_acceptance.json").read_text(encoding="utf-8"))["records"]
    report = render(root)
    for record in records:
        assert report.count("| " + record["function_id"] + ": ") == 1
    assert "TODO: write the user journey" in report
    assert "Written does not mean passed or fully covered" in report
    assert "Shared Workspace" in report
    known = {record["function_id"] for record in records}
    assert all(feature in known for case in CASES for feature in case["features"])


def test_independent_journeys_continue_but_failed_prerequisites_still_block(tmp_path, monkeypatch):
    # This tests reporting/control flow with a fake UI, not application behavior.
    # An earlier red result must stay red while unrelated stories still execute.
    from scripts.user_journeys import scenarios

    visited = []

    def fail(app):
        visited.append("failed")
        raise AssertionError("deliberate prerequisite failure")

    def succeed(app):
        visited.append("independent")
        app.ui()

    def forbidden(app):
        pytest.fail("A failed prerequisite must block this story")

    def case(name, function, requires=()):
        return {"id": name, "function": function, "phase": "basics", "independent": True, "requires": list(requires)}

    class Supervisor:
        def call(self, worker, method, params, timeout):
            if worker == "native":
                return {"debug": {"external_boundary": "synthetic desktop input"}}
            return {"extended": {}, "screenshots": ["component-test-placeholder.png"]}

    monkeypatch.setenv("OPENWAND_E2E_STATE", str(tmp_path))
    monkeypatch.setenv("OPENWAND_E2E_OUTPUT", str(tmp_path))
    monkeypatch.setenv("OPENWAND_E2E_PHASE", "basics")
    monkeypatch.delenv("OPENWAND_E2E_DEBUG_START", raising=False)
    monkeypatch.setattr(scenarios, "CASES", [case("prerequisite", fail), case("unrelated", succeed), case("dependent", forbidden, ["prerequisite"])])
    results = scenarios.run_journeys(Supervisor())
    assert visited == ["failed", "independent"]
    assert [row["status"] for row in results] == ["failed", "passed", "blocked"]
    assert "deliberate prerequisite failure" in results[0]["error"]
    assert validate_execution(results), "Continuing independent work must not make the overall run green"


def test_ci_coverage_checklist_links_to_the_tested_github_revision(monkeypatch):
    # Downloaded CI artifacts must link to the actual commit, rather than to
    # private runner filesystem paths that the reviewer cannot open.
    from scripts.user_journeys.coverage_plan import render

    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/product")
    monkeypatch.setenv("GITHUB_SHA", "abc123")
    report = render(root)
    assert "https://github.com/example/product/blob/abc123/" in report
    assert root.as_posix() not in report
    assert "#L" in report


def test_acceptance_oauth_paths_require_marked_disposable_state(tmp_path, monkeypatch):
    # Test mode must refuse an unmarked directory before any credential cache
    # can be consulted, and must never resolve names outside its auth folder.
    from core.auth.acceptance_state import isolated_auth_file

    monkeypatch.setenv("OPENWAND_USER_JOURNEYS", "1")
    monkeypatch.setenv("OPENWAND_E2E_STATE", str(tmp_path))
    with pytest.raises(RuntimeError, match="marked disposable OAuth state"):
        isolated_auth_file("codex-auth.json")
    (tmp_path / ".user-journey-state").touch()
    assert isolated_auth_file("codex-auth.json") == tmp_path / "auth-cache" / "codex-auth.json"
    with pytest.raises(ValueError, match="plain filenames"):
        isolated_auth_file("../personal-auth.json")


def test_fresh_acceptance_process_does_not_inherit_personal_oauth_caches(tmp_path):
    # Import the real auth modules in a clean child process, as worker startup
    # does. All three legacy/native paths and vault reads must be disposable.
    import json
    import os
    import subprocess
    import sys

    (tmp_path / ".user-journey-state").touch()
    env = dict(os.environ, OPENWAND_USER_JOURNEYS="1", OPENWAND_E2E_STATE=str(tmp_path),
               PYTHON_KEYRING_BACKEND="scripts.user_journeys.keyring_backend.DisposableKeyring")
    code = """import json
from core.auth import chatgpt, github
print(json.dumps({'paths': [str(chatgpt._TOKEN_FILE), str(chatgpt._codex_auth_path()), str(github._TOKEN_FILE)],
                  'signed_in': [bool(chatgpt.get_tokens()), bool(github.get_tokens())]}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[2],
                            env=env, text=True, capture_output=True, timeout=15, check=True)
    observed = json.loads(result.stdout)
    assert observed["signed_in"] == [False, False]
    assert all(Path(path).is_relative_to(tmp_path / "auth-cache") for path in observed["paths"])
