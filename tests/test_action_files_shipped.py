"""Loading checks over the action files OpenWand actually ships.

This is the gate the old hardcoded action list could never have: every shipped
file is parsed, every binding is resolved, and every capability an action names
is checked against the real registry. An action pointing at something that has
been renamed or removed fails here rather than in front of a user.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.action_files import CONTEXT_SOURCES, ActionFile, load_catalog
from core.action_files.templates import is_known_template, resolve_action
from core.actions.adapters.account.capabilities import calendar_capabilities, email_capabilities
from core.actions.adapters.browser.capabilities import browser_capabilities
from core.actions.adapters.calc.capabilities import calc_capabilities
from core.actions.adapters.excel.capabilities import excel_capabilities
from core.actions.adapters.presentation.capabilities import presentation_capabilities
from core.actions.adapters.spreadsheet_advanced import spreadsheet_advanced_capabilities
from core.actions.adapters.vscode.capabilities import vscode_capabilities

SHIPPED = Path(__file__).resolve().parents[1] / "assets" / "callers"


def _known_capabilities() -> set[str]:
    """Return every capability type an action file is allowed to name."""
    capabilities = (
        *excel_capabilities(),
        *email_capabilities(),
        *calendar_capabilities(),
        *browser_capabilities(),
        *calc_capabilities(),
        *presentation_capabilities(),
        *spreadsheet_advanced_capabilities("google_sheets"),
        *vscode_capabilities(),
    )
    return {item.type for item in capabilities}


@pytest.fixture(scope="module")
def catalog():
    """Load the shipped catalogue once."""
    return load_catalog(SHIPPED)


def _every_action(catalog) -> list[ActionFile]:
    """Return every action in the catalogue, from callers and app folders."""
    rows = [item.action for caller in catalog.callers for item in caller.actions]
    rows.extend(item.action for app in catalog.apps for item in app.actions)
    return rows


def test_the_shipped_tree_loads_without_a_single_issue(catalog) -> None:
    assert [f"{issue.code}: {issue.path} — {issue.message}" for issue in catalog.issues] == []


def test_both_built_in_callers_are_present_and_bound(catalog) -> None:
    assert [(item.folder, item.hotkey) for item in catalog.callers] == [
        ("general", "ctrl+q"),
        ("rewrite", "ctrl+shift+q"),
    ]


def test_every_shipped_action_names_a_template_or_its_own_text(catalog) -> None:
    for action in _every_action(catalog):
        assert action.template or action.label, action.path


def test_every_template_id_used_by_a_shipped_file_exists(catalog) -> None:
    for action in _every_action(catalog):
        if action.template:
            assert is_known_template(action.template), f"{action.path} names {action.template!r}"


def test_every_capability_named_by_a_shipped_file_is_registered(catalog) -> None:
    known = _known_capabilities()
    for action in _every_action(catalog):
        if action.capability and action.available:
            assert action.capability in known, f"{action.path} names {action.capability!r}"


def test_every_shipped_action_declares_its_access(catalog) -> None:
    for action in _every_action(catalog):
        assert action.access, f"{action.path} declares no ACCESS"


def test_built_in_intents_resolve_to_translated_text(catalog) -> None:
    """A shipped file carries no English; the template supplies every language."""
    general = catalog.caller("general")
    assert general is not None
    what_is_this = next(item.action for item in general.actions if item.key == "w")

    assert what_is_this.label == ""
    english = resolve_action(what_is_this, "English")
    spanish = resolve_action(what_is_this, "Spanish")

    assert english.label == "What is this?"
    assert english.prompt.startswith("What is this?")
    assert spanish.label == "¿Qué es esto?"
    assert spanish.prompt != english.prompt


def test_the_rewrite_caller_pastes_back_and_general_does_not(catalog) -> None:
    general = catalog.caller("general")
    rewrite = catalog.caller("rewrite")
    assert general is not None
    assert rewrite is not None

    assert general.settings["paste_back"] is False
    assert rewrite.settings["paste_back"] is True


@pytest.mark.parametrize(
    "surface",
    [
        {"process_name": "pycharm64.exe", "title": "main.py – demo – PyCharm"},
        {"process_name": "idea64.exe", "title": "Main.java – demo – IntelliJ IDEA"},
        {"process_name": "devenv.exe", "title": "demo - Microsoft Visual Studio"},
        {"process_name": "eclipse.exe", "title": "main.py - demo - Eclipse IDE"},
        {"process_name": "sublime_text.exe", "title": "main.py - Sublime Text"},
        {"process_name": "nvim.exe", "title": "main.py - Neovim"},
    ],
)
def test_other_code_editors_offer_the_same_app_aware_actions(catalog, surface) -> None:
    app = catalog.detect_app(surface)

    assert app is not None
    assert app.folder == "code_editors"
    assert [(item.key, item.action.capability) for item in app.actions] == [
        ("f", "vscode.replace_selection@1"),
        ("r", "vscode.replace_selection@1"),
    ]


def test_shipped_actions_inherit_paste_back_from_their_caller(catalog) -> None:
    """No built-in overrides paste_back; the caller decides, exactly as today."""
    for caller in catalog.callers:
        for item in caller.actions:
            assert item.action.paste_back is None, item.action.path


def test_every_caller_stores_its_context_by_source_id(catalog) -> None:
    """Keyed by id, never by position, so a number always means the same source."""
    for caller in catalog.callers:
        context = caller.settings.get("context")
        assert isinstance(context, dict), caller.folder
        assert set(context) == set(CONTEXT_SOURCES), caller.folder


def test_no_shipped_action_ships_a_script_yet(catalog) -> None:
    """Every built-in is a prompt or a typed capability, so none carries code."""
    for action in _every_action(catalog):
        assert action.has_code is False, action.path


def test_excel_actions_are_bound_and_detect_the_real_process(catalog) -> None:
    excel = next(app for app in catalog.apps if app.folder == "excel")

    assert [(item.key, item.action.capability) for item in excel.actions] == [
        ("c", "excel.add_chart@1"),
        ("t", "excel.create_table@1"),
        ("o", "excel.sort_range@1"),
        ("a", ""),
        ("u", ""),
        ("r", ""),
        ("m", ""),
        ("e", "excel.clean_range@1"),
        ("f", ""),
    ]
    assert catalog.detect_app({"process_name": "EXCEL.EXE"}) is not None
    assert catalog.detect_app({"process_name": "notepad.exe"}) is None


def test_excel_rows_join_the_general_menu_without_taking_a_built_in_letter(catalog) -> None:
    rows = catalog.menu_for("general", {"process_name": "excel.exe"})

    assert [item.key for item in rows] == ["w", "a", "d", "u", "r", "m", "e", "f"]


def test_excel_and_calc_offer_the_same_core_spreadsheet_goals(catalog) -> None:
    """Switching desktop spreadsheet apps keeps the core action vocabulary."""
    excel = next(app for app in catalog.apps if app.folder == "excel")
    calc = next(app for app in catalog.apps if app.folder == "libreoffice_calc")

    def labels(app) -> set[str]:
        return {item.action.label for item in app.actions}

    shared = {
        "Find outliers in this data",
        "Find trends and relationships",
        "Summarize this data",
        "Clean up this export",
        "Explain formula",
    }
    assert shared <= labels(excel)
    assert shared <= labels(calc)

    for app in (excel, calc):
        visible = {item.action.label for item in app.actions if item.action.show_in_picker}
        assert visible == shared
        cleanup = next(item.action for item in app.actions if item.action.name == "clean_export")
        assert [access.value for access in cleanup.access] == ["files"]


def test_word_writer_and_google_docs_offer_the_same_read_only_document_goals(catalog) -> None:
    """Switching desktop document apps keeps the same AI-first vocabulary."""
    word = next(app for app in catalog.apps if app.folder == "word_desktop")
    writer = next(app for app in catalog.apps if app.folder == "libreoffice_writer")
    docs = next(app for app in catalog.apps if app.folder == "google_docs")
    shared = {
        "Summarize this document",
        "Explain the selected passage",
        "Draft a rewrite of this passage",
        "Find inconsistencies and contradictions",
        "Extract action items",
        "Build an outline from this document",
    }

    for app in (word, writer, docs):
        assert {item.action.label for item in app.actions if item.action.show_in_picker} == shared
        assert all(not item.action.capability and not item.action.paste_back for item in app.actions)

    assert catalog.detect_app({"process_name": "WINWORD.EXE"}) == word
    assert catalog.detect_app({
        "process_name": "soffice.bin",
        "title": "Draft.odt — LibreOffice Writer",
    }) == writer
    assert catalog.detect_app({
        "process_name": "soffice.bin",
        "title": "Budget.ods — LibreOffice Calc",
    }).folder == "libreoffice_calc"
    assert catalog.detect_app({
        "process_name": "chrome.exe",
        "browser_url": "https://docs.google.com/document/d/example/edit",
    }) == docs
    assert catalog.detect_app({
        "process_name": "chrome.exe",
        "browser_url": "https://docs.google.com/spreadsheets/d/example/edit",
    }).folder == "google_sheets"
    assert catalog.detect_app({
        "process_name": "chrome.exe",
        "browser_url": "https://docs.google.com/presentation/d/example/edit",
    }).folder == "google_slides"


def test_presentation_alternatives_share_ai_first_read_only_goals(catalog) -> None:
    folders = (
        "powerpoint_desktop",
        "powerpoint_web",
        "google_slides",
        "libreoffice_impress",
    )
    shared = {
        "Summarize this deck",
        "Find story and logic gaps",
        "Draft an agenda",
        "Improve the selected slide's message",
        "Check consistency across slides",
    }
    expected_keys = {
        "summarize_deck": "s",
        "find_story_gaps": "g",
        "draft_agenda": "a",
        "improve_slide_message": "m",
        "check_slide_consistency": "k",
    }

    for folder in folders:
        app = next(item for item in catalog.apps if item.folder == folder)
        prompt_actions = {
            bound.action.name: bound
            for bound in app.actions
            if bound.action.label in shared
        }
        assert {bound.action.label for bound in prompt_actions.values()} == shared
        assert {name: bound.key for name, bound in prompt_actions.items()} == expected_keys
        assert all(
            not bound.action.capability
            and not bound.action.has_code
            and [access.value for access in bound.action.access] == ["text"]
            for bound in prompt_actions.values()
        )

    impress = next(item for item in catalog.apps if item.folder == "libreoffice_impress")
    assert catalog.detect_app({"process_name": "SIMPress.EXE"}) == impress
    assert catalog.detect_app({
        "process_name": "soffice.bin",
        "title": "Pitch.odp — LibreOffice Impress",
    }) == impress
    assert catalog.detect_app({"process_name": "soffice.bin"}) is None
    assert catalog.detect_app({
        "process_name": "soffice.bin",
        "title": "Notes.odt — LibreOffice Writer",
    }).folder == "libreoffice_writer"
    assert catalog.detect_app({
        "process_name": "soffice.bin",
        "title": "Budget.ods — LibreOffice Calc",
    }).folder == "libreoffice_calc"
