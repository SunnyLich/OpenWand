"""Loading the action-file catalogue from a folder tree.

An action is a pair: name.toml describes it, name.py optionally holds its code.
"""

from __future__ import annotations

from pathlib import Path

from core.action_files import (
    Access,
    load_catalog,
    lookup_report,
    parse_action_file,
    run_action_script,
    save_callers,
)
from core.action_files.store import ActionCatalogStore, action_runtime_copy, action_runtime_route, caller_row

PROMPT_ACTION = """
label = "Fix grammar"
hint = "Tidy up the writing"
prompt = "Fix the grammar in this text."
context = ["selection"]
paste_back = true
access = ["text"]
"""

CODE_ACTION = """
label = "Add chart"
prompt = "Create a chart from the selected cells."
capability = "excel.add_chart@1"
planner = "excel_plan_add_chart"
run_script_first = true
access = ["files", "programs"]
"""

SCRIPT = "def run(ctx):\n    return ctx\n"


def _tree(root: Path, callers: dict, folders: dict[str, dict[str, str]]) -> None:
    """Write a callers/ tree. folders maps folder name to filename -> contents."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "callers.toml").write_text(_callers_toml(callers), encoding="utf-8")
    for name, files in folders.items():
        folder = root / name
        folder.mkdir(parents=True, exist_ok=True)
        for filename, contents in files.items():
            (folder / filename).write_text(contents, encoding="utf-8")


def _quick(root: Path, files: dict[str, str]) -> None:
    """Write a single 'quick' caller bound to ctrl+q."""
    _tree(root, {"callers": [{"folder": "quick", "hotkey": "ctrl+q"}]}, {"quick": files})


def _written(path: Path, contents: str) -> Path:
    """Write a file and return its path."""
    path.write_text(contents, encoding="utf-8")
    return path


def test_existing_live_tree_merges_new_shipped_actions_without_overwriting_user_files(
    tmp_path: Path,
) -> None:
    shipped = tmp_path / "shipped"
    live = tmp_path / "live"
    for root in (shipped, live):
        (root / "app" / "excel").mkdir(parents=True)
    (shipped / "app" / "excel" / "keys.toml").write_text(
        'c = "add_chart"\no = "sort_range"\na = "analyze_selection"\n',
        encoding="utf-8",
    )
    (shipped / "app" / "excel" / "add_chart.toml").write_text(
        'label = "Create a chart"\nprompt = "Chart it"\n', encoding="utf-8"
    )
    (shipped / "app" / "excel" / "sort_range.toml").write_text(
        'label = "Sort this table"\nprompt = "Sort it"\n', encoding="utf-8"
    )
    (shipped / "app" / "excel" / "analyze_selection.toml").write_text(
        'label = "Analyze this data"\nprompt = "Analyze it"\n', encoding="utf-8"
    )
    user_chart = '# user edit\nlabel = "My chart"\nprompt = "Keep this"\n'
    (live / "app" / "excel" / "keys.toml").write_text(
        'c = "add_chart"\n', encoding="utf-8"
    )
    (live / "app" / "excel" / "add_chart.toml").write_text(user_chart, encoding="utf-8")

    ActionCatalogStore(live, shipped).ensure_seeded()

    assert (live / "app" / "excel" / "add_chart.toml").read_text(encoding="utf-8") == user_chart
    assert (live / "app" / "excel" / "sort_range.toml").is_file()
    assert (live / "app" / "excel" / "analyze_selection.toml").is_file()
    keys = (live / "app" / "excel" / "keys.toml").read_text(encoding="utf-8")
    assert 'c = "add_chart"' in keys
    assert 'o = "sort_range"' in keys
    assert 'a = "analyze_selection"' in keys


def test_legacy_cleanup_route_upgrades_without_converting_custom_actions() -> None:
    route = action_runtime_route(
        "excel",
        "clean_export",
        "",
        "",
        label="Clean up this export",
        hint="Find cleanup problems and propose exact, reviewable fixes",
        prompt=(
            "Produce a precise cleanup plan, and do not change cells until a reviewed "
            "cleanup capability is available."
        ),
    )
    custom = action_runtime_route(
        "excel",
        "clean_export",
        "",
        "",
        label="My cleanup report",
        hint="Only report",
        prompt="Never edit cells.",
    )

    assert route == ("excel.clean_range@1", "excel_plan_clean_range")
    assert custom == ("", "")


def test_legacy_formula_copy_upgrades_without_rewording_custom_actions() -> None:
    legacy = action_runtime_copy(
        "libreoffice_calc",
        "explain_formula",
        "Explain the selected formula",
        "Describe its inputs and logic, then flag likely mistakes",
        (
            "Explain the selected spreadsheet formula in plain language, including its inputs, logic, and output. "
            "Flag broken references, risky assumptions, or inconsistencies with neighboring formulas. If no formula "
            "text is available, say exactly what the user needs to select. Do not change any cells."
        ),
    )
    custom = action_runtime_copy(
        "libreoffice_calc",
        "explain_formula",
        "Explain my model",
        "Use our accounting conventions",
        "Explain this using the team's terminology.",
    )

    assert legacy[:2] == (
        "Explain formula",
        "Describe its inputs and logic, then flag likely mistakes",
    )
    assert custom == (
        "Explain my model",
        "Use our accounting conventions",
        "Explain this using the team's terminology.",
    )


def test_prompt_only_action_needs_no_script_and_runs_inline(tmp_path: Path) -> None:
    _quick(tmp_path, {"keys.toml": _keys_toml({"g": "grammar"}), "grammar.toml": PROMPT_ACTION})

    catalog = load_catalog(tmp_path)

    assert catalog.issues == ()
    row = catalog.callers[0].actions[0]
    assert row.key == "g"
    assert row.action.label == "Fix grammar"
    assert row.action.context == ("selection",)
    assert row.action.paste_back is True
    assert row.action.has_code is False
    assert row.action.runs_in_process is True


def test_disabled_action_loads_for_settings_but_stays_out_of_the_menu(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {
            "keys.toml": _keys_toml({"g": "grammar"}),
            "grammar.toml": PROMPT_ACTION + "\nenabled = false\n",
        },
    )

    catalog = load_catalog(tmp_path)

    assert not catalog.callers[0].actions[0].action.enabled
    assert catalog.menu_for("quick") == ()


def test_action_can_stay_available_to_the_planner_without_showing_in_the_picker(
    tmp_path: Path,
) -> None:
    _quick(
        tmp_path,
        {
            "keys.toml": _keys_toml({"g": "grammar"}),
            "grammar.toml": PROMPT_ACTION + "\nshow_in_picker = false\n",
        },
    )

    catalog = load_catalog(tmp_path)

    assert catalog.issues == ()
    assert catalog.callers[0].actions[0].action.show_in_picker is False
    assert catalog.menu_for("quick") == ()


def test_a_script_beside_the_action_makes_it_a_code_action(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {"keys.toml": _keys_toml({"c": "chart"}), "chart.toml": CODE_ACTION, "chart.py": SCRIPT},
    )

    action = load_catalog(tmp_path).callers[0].actions[0].action

    assert action.has_code is True
    assert action.runs_in_process is False
    assert action.run_script_first is True
    assert Path(action.script_path).name == "chart.py"


def test_drawing_a_menu_never_imports_the_script(tmp_path: Path) -> None:
    """The description file is data; the script is untouched until it is chosen."""
    sentinel = tmp_path / "imported.txt"
    script = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('ran')\n"
    _quick(
        tmp_path,
        {"keys.toml": _keys_toml({"c": "chart"}), "chart.toml": CODE_ACTION, "chart.py": script},
    )

    catalog = load_catalog(tmp_path)

    assert not sentinel.exists()
    assert catalog.callers[0].actions[0].action.has_code is True


def test_selected_script_runs_out_of_process_and_receives_model_response(tmp_path: Path) -> None:
    action_path = _written(
        tmp_path / "postprocess.toml",
        'label = "Post-process"\nprompt = "Improve this"\naccess = ["text"]\n',
    )
    _written(
        action_path.with_suffix(".py"),
        "def run(payload):\n"
        "    return {'output': payload['model_response'].upper()}\n",
    )
    action, issues = parse_action_file(action_path)

    assert issues == ()
    assert action is not None
    result = run_action_script(
        action,
        context={"selected_text": "hello"},
        prompt="Improve this",
        model_response="better text",
    )

    assert result.output == "BETTER TEXT"


def test_settings_edits_preserve_toml_comments(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {
            "caller.toml": '# caller note\nlabel = "Quick" # keep inline\n[context]\nselection = "on" # source note\n',
            "keys.toml": '# key note\ng = "grammar" # binding note\n',
            "grammar.toml": '# action note\nlabel = "Fix grammar"\nprompt = "Fix it"\naccess = ["text"]\n',
        },
    )
    callers_path = tmp_path / "callers.toml"
    callers_path.write_text(
        '# registry note\n[[callers]]\nfolder = "quick"\nhotkey = "ctrl+q" # hotkey note\n',
        encoding="utf-8",
    )

    save_callers(
        tmp_path,
        [
            {
                "folder": "quick",
                "hotkey": "ctrl+shift+q",
                "enabled": True,
                "label": "Quick edits",
                "paste_back": False,
                "context": {"selection": "on"},
                "actions": [
                    {
                        "name": "grammar",
                        "key": "f",
                        "label": "Fix it",
                        "prompt": "Fix this text",
                        "enabled": False,
                    }
                ],
            }
        ],
    )

    combined = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.toml"))
    assert "# registry note" in combined
    assert "# hotkey note" in combined
    assert "# caller note" in combined
    assert "# keep inline" in combined
    assert "# source note" in combined
    assert "# key note" in combined
    assert "# binding note" in combined
    assert "# action note" in combined
    catalog = load_catalog(tmp_path)
    assert catalog.issues == ()
    assert not catalog.callers[0].actions[0].action.enabled
    assert catalog.menu_for("quick") == ()


def test_runtime_caller_preserves_exact_file_access_mode(tmp_path: Path) -> None:
    """The compatibility row must not collapse read access into ask access."""
    _quick(
        tmp_path,
        {
            "caller.toml": 'label = "Quick"\nfile_access = "read"\n[context]\nfiles = "on"\n',
        },
    )

    catalog = load_catalog(tmp_path)

    assert catalog.issues == ()
    assert caller_row(catalog.callers[0])["file_access"] == "read"


def test_a_script_with_no_description_file_is_reported(tmp_path: Path) -> None:
    """Renaming one half of the pair must not silently detach them."""
    _quick(tmp_path, {"grammar.toml": PROMPT_ACTION, "stray.py": SCRIPT})

    catalog = load_catalog(tmp_path)

    assert [issue.code for issue in catalog.issues] == ["orphan_script"]


def test_run_script_first_without_a_script_is_reported(tmp_path: Path) -> None:
    _quick(tmp_path, {"chart.toml": CODE_ACTION})

    catalog = load_catalog(tmp_path)

    assert [issue.code for issue in catalog.issues] == ["no_script"]


def test_a_broken_description_is_reported_and_skipped(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {
            "keys.toml": _keys_toml({"g": "grammar", "b": "broken"}),
            "grammar.toml": PROMPT_ACTION,
            "broken.toml": 'label = "Broken\n',
        },
    )

    catalog = load_catalog(tmp_path)

    assert [item.action.label for item in catalog.callers[0].actions] == ["Fix grammar"]
    assert [issue.code for issue in catalog.issues] == ["bad_toml", "missing_action"]


def test_an_unknown_setting_is_reported(tmp_path: Path) -> None:
    action, issues = parse_action_file(
        _written(tmp_path / "odd.toml", 'label = "Odd"\nprompt = "x"\npast_back = true\n')
    )

    assert action is not None
    assert [issue.code for issue in issues] == ["unknown_field"]


def test_an_action_that_does_nothing_is_refused(tmp_path: Path) -> None:
    action, issues = parse_action_file(_written(tmp_path / "empty.toml", 'label = "Nothing"\n'))

    assert action is None
    assert [issue.code for issue in issues] == ["does_nothing"]


def test_an_unlisted_action_shows_without_a_key(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {
            "keys.toml": _keys_toml({"g": "grammar"}),
            "grammar.toml": PROMPT_ACTION,
            "extra.toml": PROMPT_ACTION.replace("Fix grammar", "Just dropped in"),
        },
    )

    rows = load_catalog(tmp_path).callers[0].actions

    assert [(item.key, item.action.label) for item in rows] == [
        ("g", "Fix grammar"),
        ("", "Just dropped in"),
    ]


def test_private_helpers_are_not_actions(tmp_path: Path) -> None:
    _quick(tmp_path, {"grammar.toml": PROMPT_ACTION, "_shared.toml": 'label = "x"\n', "_util.py": SCRIPT})

    catalog = load_catalog(tmp_path)

    assert [item.action.name for item in catalog.callers[0].actions] == ["grammar"]
    assert catalog.issues == ()


def test_a_key_pointing_at_a_missing_action_is_reported(tmp_path: Path) -> None:
    _quick(tmp_path, {"keys.toml": _keys_toml({"g": "gone"}), "grammar.toml": PROMPT_ACTION})

    catalog = load_catalog(tmp_path)

    assert [issue.code for issue in catalog.issues] == ["missing_action"]
    assert [item.key for item in catalog.callers[0].actions] == [""]


def test_a_key_may_name_the_file_or_just_the_action(tmp_path: Path) -> None:
    _quick(tmp_path, {"keys.toml": _keys_toml({"g": "grammar.toml"}), "grammar.toml": PROMPT_ACTION})

    assert load_catalog(tmp_path).callers[0].actions[0].key == "g"


def test_an_invalid_key_is_reported(tmp_path: Path) -> None:
    _quick(tmp_path, {"keys.toml": _keys_toml({"ctrl+g": "grammar"}), "grammar.toml": PROMPT_ACTION})

    assert [issue.code for issue in load_catalog(tmp_path).issues] == ["bad_key"]


def test_access_colour_takes_the_most_serious_declared(tmp_path: Path) -> None:
    _quick(tmp_path, {"chart.toml": CODE_ACTION, "chart.py": SCRIPT})

    action = load_catalog(tmp_path).callers[0].actions[0].action

    assert action.access == (Access.FILES, Access.PROGRAMS)
    assert action.colour == "red"


def test_unknown_access_is_reported(tmp_path: Path) -> None:
    action, issues = parse_action_file(
        _written(tmp_path / "odd.toml", 'label = "Odd"\nprompt = "x"\naccess = ["telepathy"]\n')
    )

    assert action is not None
    assert action.access == ()
    assert [issue.code for issue in issues] == ["unknown_access"]


def test_structural_files_are_never_read_as_actions(tmp_path: Path) -> None:
    """caller.toml and keys.toml share the action suffix; they are not actions."""
    _quick(
        tmp_path,
        {
            "caller.toml": _caller_toml({"label": "Quick", "paste_back": False}),
            "keys.toml": _keys_toml({"g": "grammar"}),
            "grammar.toml": PROMPT_ACTION,
        },
    )

    catalog = load_catalog(tmp_path)

    assert catalog.issues == ()
    assert [item.action.name for item in catalog.callers[0].actions] == ["grammar"]


def test_an_unknown_context_source_in_caller_toml_is_reported(tmp_path: Path) -> None:
    _quick(
        tmp_path,
        {
            "caller.toml": _caller_toml({"context": {"selection": "on", "telepathy": "on"}}),
            "grammar.toml": PROMPT_ACTION,
        },
    )

    assert [issue.code for issue in load_catalog(tmp_path).issues] == ["unknown_context"]


def test_missing_root_reports_instead_of_raising(tmp_path: Path) -> None:
    catalog = load_catalog(tmp_path / "not-here")

    assert catalog.callers == ()
    assert [issue.code for issue in catalog.issues] == ["no_root"]


def test_a_caller_with_no_hotkey_is_reported_as_unreachable(tmp_path: Path) -> None:
    _tree(tmp_path, {"callers": [{"folder": "quick"}]}, {"quick": {"grammar.toml": PROMPT_ACTION}})

    catalog = load_catalog(tmp_path)

    assert [issue.code for issue in catalog.issues] == ["no_hotkey"]
    assert catalog.callers[0].hotkey == ""


# --- app folders ---


def _with_app(tmp_path: Path, folder: str, manifest: dict, files: dict[str, str]) -> Path:
    """Write a quick caller plus one app folder."""
    _quick(tmp_path, {"keys.toml": _keys_toml({"g": "grammar"}), "grammar.toml": PROMPT_ACTION})
    app = tmp_path / "app" / folder
    app.mkdir(parents=True, exist_ok=True)
    (app / "app.toml").write_text(_app_toml(manifest), encoding="utf-8")
    for name, contents in files.items():
        (app / name).write_text(contents, encoding="utf-8")
    return app


def test_app_folder_matches_on_process_or_title(tmp_path: Path) -> None:
    _with_app(
        tmp_path,
        "excel",
        {"display_name": "Microsoft Excel", "match": {"process": ["excel.exe"], "title": ["microsoft excel"]}},
        {"chart.toml": CODE_ACTION, "chart.py": SCRIPT},
    )

    catalog = load_catalog(tmp_path)

    assert catalog.detect_app({"process_name": "EXCEL.EXE"}) is not None
    assert catalog.detect_app({"title": "Book1 - Microsoft Excel"}) is not None
    assert catalog.detect_app({"process_name": "notepad.exe"}) is None


def test_web_apps_match_on_the_browser_address(tmp_path: Path) -> None:
    _with_app(
        tmp_path,
        "sheets",
        {"display_name": "Google Sheets", "match": {"url": ["docs.google.com/spreadsheets/"]}},
        {"grammar.toml": PROMPT_ACTION},
    )

    catalog = load_catalog(tmp_path)

    assert catalog.detect_app({"browser_url": "https://docs.google.com/spreadsheets/d/abc"}) is not None
    assert catalog.detect_app({"browser_url": "https://docs.google.com/document/d/abc"}) is None


def test_priority_decides_which_app_wins(tmp_path: Path) -> None:
    _with_app(tmp_path, "browser", {"match": {"process": ["chrome.exe"]}}, {"a.toml": PROMPT_ACTION})
    sheets = tmp_path / "app" / "sheets"
    sheets.mkdir(parents=True)
    (sheets / "app.toml").write_text(
        _app_toml({"display_name": "Google Sheets", "priority": 10, "match": {"process": ["chrome.exe"]}}),
        encoding="utf-8",
    )
    (sheets / "b.toml").write_text(PROMPT_ACTION, encoding="utf-8")

    detected = load_catalog(tmp_path).detect_app({"process_name": "chrome.exe"})

    assert detected is not None
    assert detected.folder == "sheets"


def test_an_app_folder_with_nothing_to_match_is_reported(tmp_path: Path) -> None:
    _with_app(tmp_path, "mystery", {"display_name": "Mystery"}, {"a.toml": PROMPT_ACTION})

    catalog = load_catalog(tmp_path)

    assert [issue.code for issue in catalog.issues] == ["no_match"]
    assert catalog.apps == ()


def test_app_actions_join_the_menu_but_never_take_your_letter(tmp_path: Path) -> None:
    _with_app(
        tmp_path,
        "excel",
        {"display_name": "Microsoft Excel", "match": {"process": ["excel.exe"]}},
        {
            "keys.toml": _keys_toml({"g": "clash", "c": "chart"}),
            "clash.toml": PROMPT_ACTION,
            "chart.toml": CODE_ACTION,
            "chart.py": SCRIPT,
        },
    )

    rows = load_catalog(tmp_path).menu_for("quick", {"process_name": "excel.exe"})

    assert [(item.key, item.action.label) for item in rows] == [
        ("g", "Fix grammar"),
        ("", "Fix grammar"),
        ("c", "Add chart"),
    ]


def test_a_menu_over_an_unknown_app_is_just_your_own_actions(tmp_path: Path) -> None:
    _with_app(
        tmp_path,
        "excel",
        {"match": {"process": ["excel.exe"]}},
        {"chart.toml": CODE_ACTION, "chart.py": SCRIPT},
    )

    rows = load_catalog(tmp_path).menu_for("quick", {"process_name": "notepad.exe"})

    assert [item.action.label for item in rows] == ["Fix grammar"]


def test_lookup_report_lists_every_app_and_action(tmp_path: Path) -> None:
    _with_app(
        tmp_path,
        "excel",
        {"display_name": "Microsoft Excel", "match": {"process": ["excel.exe"]}},
        {"keys.toml": _keys_toml({"c": "chart"}), "chart.toml": CODE_ACTION, "chart.py": SCRIPT},
    )

    report = lookup_report(load_catalog(tmp_path))

    assert "Microsoft Excel" in report
    assert "process: excel.exe" in report
    assert "[c] Add chart" in report


# --- TOML fixture writers ---


def _scalar(value: object) -> str:
    """Render one TOML value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_scalar(item) for item in value) + "]"
    return '"' + str(value).replace('"', '\\"') + '"'


def _table(value: dict, name: str) -> str:
    """Render a flat table with one named sub-table last."""
    lines = [f"{key} = {_scalar(item)}" for key, item in value.items() if key != name]
    nested = value.get(name)
    if isinstance(nested, dict):
        lines.append(f"\n[{name}]")
        lines.extend(f"{key} = {_scalar(item)}" for key, item in nested.items())
    return "\n".join(lines) + "\n"


def _callers_toml(value: dict) -> str:
    """Render a callers.toml from the shorthand used by these tests."""
    blocks = [
        "\n".join(["[[callers]]", *(f"{key} = {_scalar(item)}" for key, item in entry.items())])
        for entry in value.get("callers", [])
    ]
    return "\n\n".join(blocks) + "\n"


def _keys_toml(value: dict) -> str:
    """Render a keys.toml mapping letters to action names."""
    return "".join(f'"{key}" = {_scalar(item)}\n' for key, item in value.items())


def _caller_toml(value: dict) -> str:
    """Render a caller.toml, putting the context table last."""
    return _table(value, "context")


def _app_toml(value: dict) -> str:
    """Render an app.toml, putting the match table last."""
    return _table(value, "match")
