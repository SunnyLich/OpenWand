"""Tests for context_fetcher's snapshot, prompt-formatting, and resolver helpers.

Covers the OS-independent half of core/context_fetcher.py that the per-OS
context tests skip: prompt formatting, snapshot persistence and reload,
config-dir/URI decoding, filename resolution through folders, VS Code
storage.json and Obsidian vaults, recent-file listings, and the online-search
public-search delegation and failures. Everything runs against temp
directories and canned payloads; no native APIs or network.
"""
from __future__ import annotations

import json
import os
import sys
import time

import pytest

import core.context_fetcher as context_fetcher
from core.context_fetcher import (
    ClipboardInfo,
    ContextSnapshot,
    UIElementInfo,
    WindowInfo,
    format_context_for_prompt,
)


def _file_uri(path) -> str:
    return "file:///" + str(path).replace(os.sep, "/").lstrip("/")


def _xbel_uri(path) -> str:
    """href whose text after ``file://`` is a valid native path on this OS."""
    return "file://" + str(path).replace(os.sep, "/")


# ---------------------------------------------------------------------------
# format_context_for_prompt
# ---------------------------------------------------------------------------


def test_format_context_includes_every_populated_source():
    snapshot = ContextSnapshot(
        active_window=WindowInfo(
            title="notes.txt - Notepad", process_name="notepad.exe", url="https://example.com/page"
        ),
        clipboard=ClipboardInfo(text="copied\nvalue", fmt="text"),
        ui_focused=UIElementInfo(
            name="Body", value="line one\nline two", control_type="Edit", window_title="notes.txt"
        ),
        fs_events=[f"change-{i}" for i in range(7)],
        browser_content="Page text here.",
    )

    prompt = format_context_for_prompt(snapshot)

    assert prompt.startswith("AMBIENT CONTEXT (captured at hotkey time):")
    assert "- Active window: notepad.exe — “notes.txt - Notepad”" in prompt
    assert "- Browser URL: https://example.com/page" in prompt
    assert "[Browser/Web]\nPage text here." in prompt
    assert "- Clipboard: “copied value”" in prompt
    assert "- Focused element: Edit ‘Body’ in “notes.txt”" in prompt
    assert "- Element value: “line one line two”" in prompt
    # Only the five newest fs events are listed.
    assert "- Recent file changes: change-2, change-3, change-4, change-5, change-6" in prompt
    assert "- Open document: \"notes.txt\"" in prompt
    assert "get_context tool" in prompt


def test_format_context_truncates_long_clipboard_with_ellipsis():
    snapshot = ContextSnapshot(clipboard=ClipboardInfo(text="x" * 400, fmt="text"))

    prompt = format_context_for_prompt(snapshot)

    assert "x" * 300 + "…" in prompt
    assert "x" * 301 not in prompt


def test_format_context_reports_clipboard_image():
    snapshot = ContextSnapshot(clipboard=ClipboardInfo(text="", fmt="image"))
    assert "- Clipboard: [image]" in format_context_for_prompt(snapshot)


def test_format_context_strips_bracket_suffix_from_document_names():
    snapshot = ContextSnapshot(
        active_window=WindowInfo(title="draft.md [Modified] - Notepad", process_name="notepad.exe")
    )

    prompt = format_context_for_prompt(snapshot)

    assert '- Open document: "draft.md"' in prompt
    assert "[Modified]" not in prompt.split("Open document")[1].splitlines()[0]


def test_format_context_empty_snapshot_returns_empty_string():
    assert format_context_for_prompt(ContextSnapshot()) == ""


# ---------------------------------------------------------------------------
# Snapshot persistence round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_snapshot_file(tmp_path, monkeypatch):
    path = tmp_path / "context-snapshot.json"
    monkeypatch.setattr(context_fetcher, "_TEMP_FILE", str(path))
    return path


def test_persist_and_load_latest_round_trip(temp_snapshot_file):
    snapshot = ContextSnapshot(
        timestamp=123.5,
        active_window=WindowInfo(title="Doc", process_name="app.exe"),
        clipboard=ClipboardInfo(text="clip", fmt="text"),
        recent_files=["a.txt", "b.txt"],
        online_results=[{"title": "T", "url": "https://e.com", "snippet": "s"}],
    )

    context_fetcher._persist(snapshot)

    assert context_fetcher.get_temp_path() == str(temp_snapshot_file)
    on_disk = json.loads(temp_snapshot_file.read_text(encoding="utf-8"))
    assert on_disk == context_fetcher._snapshot_to_dict(snapshot)
    assert on_disk["active_window"]["title"] == "Doc"
    assert on_disk["recent_files"] == ["a.txt", "b.txt"]
    assert context_fetcher.load_latest() == on_disk


def test_load_latest_returns_none_for_missing_or_corrupt_file(temp_snapshot_file):
    assert context_fetcher.load_latest() is None
    temp_snapshot_file.write_text("{not json", encoding="utf-8")
    assert context_fetcher.load_latest() is None


def test_persist_swallows_write_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(context_fetcher, "_TEMP_FILE", str(tmp_path))  # a directory: open() fails

    context_fetcher._persist(ContextSnapshot())

    assert "Failed to write snapshot" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Config dir and VS Code URI decoding
# ---------------------------------------------------------------------------


def test_config_dir_per_platform(monkeypatch):
    monkeypatch.setattr(context_fetcher, "_IS_WIN", True)
    monkeypatch.setenv("APPDATA", "X:\\Roaming")
    assert context_fetcher._config_dir() == "X:\\Roaming"

    monkeypatch.setattr(context_fetcher, "_IS_WIN", False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert context_fetcher._config_dir().endswith(os.path.join("Library", "Application Support"))

    monkeypatch.setattr(sys, "platform", "linux")
    assert context_fetcher._config_dir().endswith(".config")


def test_decode_vscode_uri_windows(monkeypatch):
    monkeypatch.setattr(context_fetcher, "_IS_WIN", True)
    decoded = context_fetcher._decode_vscode_uri("file:///c:/Users/Me/My%20File.txt")
    assert decoded == os.sep.join(["C:", "Users", "Me", "My File.txt"])
    assert context_fetcher._decode_vscode_uri("untitled:Untitled-1") == ""


def test_decode_vscode_uri_posix(monkeypatch):
    monkeypatch.setattr(context_fetcher, "_IS_WIN", False)
    assert context_fetcher._decode_vscode_uri("file:///home/me/a%20b.txt") == "/home/me/a b.txt"


# ---------------------------------------------------------------------------
# Filename resolution helpers
# ---------------------------------------------------------------------------


def test_search_filename_in_folders_walks_to_max_depth(tmp_path):
    nested = tmp_path / "l1" / "l2"
    nested.mkdir(parents=True)
    target = nested / "target.txt"
    target.write_text("x", encoding="utf-8")

    found = context_fetcher._search_filename_in_folders("target.txt", [str(tmp_path)])
    assert found == str(target)

    assert context_fetcher._search_filename_in_folders("missing.txt", [str(tmp_path)]) == ""
    # Depth limit is respected.
    assert context_fetcher._search_filename_in_folders("target.txt", [str(tmp_path)], max_depth=2) == ""


def test_search_filename_handles_glob_characters_in_folder_names(tmp_path):
    weird = tmp_path / "proj [main]"
    weird.mkdir()
    target = weird / "notes.md"
    target.write_text("x", encoding="utf-8")

    assert context_fetcher._search_filename_in_folders("notes.md", [str(weird)]) == str(target)


def test_vscode_find_file_prefers_exact_recent_entry(tmp_path):
    storage = tmp_path / "storage.json"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    in_workspace = workspace / "shared.py"
    in_workspace.write_text("x", encoding="utf-8")
    recent = tmp_path / "elsewhere" / "shared.py"
    storage.write_text(
        json.dumps(
            {
                "history.recentlyOpenedPathsList": {
                    "files2": [{"fileUri": _file_uri(recent)}],
                    "workspaces3": [{"folderUri": _file_uri(workspace)}],
                }
            }
        ),
        encoding="utf-8",
    )

    found = context_fetcher._vscode_find_file("shared.py", storage_path=str(storage))

    # The exact files2 entry wins even though the workspace also has the file.
    assert found == str(recent)


def test_vscode_find_file_falls_back_to_workspace_search(tmp_path):
    storage = tmp_path / "storage.json"
    workspace = tmp_path / "workspace"
    (workspace / "src").mkdir(parents=True)
    target = workspace / "src" / "deep.py"
    target.write_text("x", encoding="utf-8")
    storage.write_text(
        json.dumps(
            {
                "history.recentlyOpenedPathsList": {
                    "files2": [{"fileUri": _file_uri(tmp_path / "other.py")}],
                    "workspaces3": [{"folderUri": _file_uri(workspace)}],
                }
            }
        ),
        encoding="utf-8",
    )

    assert context_fetcher._vscode_find_file("deep.py", storage_path=str(storage)) == str(target)
    assert context_fetcher._vscode_find_file("deep.py", storage_path=str(tmp_path / "nope.json")) == ""


def test_obsidian_find_note_resolves_vault_notes(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    (vault / "daily").mkdir(parents=True)
    dashed = vault / "daily" / "Plan - Q3.md"
    dashed.write_text("x", encoding="utf-8")
    plain = vault / "Standup.md"
    plain.write_text("x", encoding="utf-8")
    config_home = tmp_path / "config"
    (config_home / "obsidian").mkdir(parents=True)
    (config_home / "obsidian" / "obsidian.json").write_text(
        json.dumps({"vaults": {"abc": {"path": str(vault)}}}), encoding="utf-8"
    )
    monkeypatch.setattr(context_fetcher, "_config_dir", lambda: str(config_home))

    # "Note - Vault" splits from the right, keeping " - " inside the note name.
    assert context_fetcher._obsidian_find_note("Plan - Q3 - Vault") == str(dashed)
    assert context_fetcher._obsidian_find_note("Standup") == str(plain)
    # Without a vault suffix the rightmost segment is still read as the vault
    # hint, so a dashed note name alone does not resolve.
    assert context_fetcher._obsidian_find_note("Plan - Q3") == ""
    assert context_fetcher._obsidian_find_note("Nope") == ""
    assert context_fetcher._obsidian_find_note("") == ""


def test_obsidian_find_note_without_storage_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(context_fetcher, "_config_dir", lambda: str(tmp_path))
    assert context_fetcher._obsidian_find_note("Anything") == ""


# ---------------------------------------------------------------------------
# Recent files
# ---------------------------------------------------------------------------


def test_fetch_recent_files_win_lists_newest_shortcuts_first(tmp_path, monkeypatch):
    recent = tmp_path / "Microsoft" / "Windows" / "Recent"
    recent.mkdir(parents=True)
    old = recent / "older.txt.lnk"
    new = recent / "newest.txt.lnk"
    skip = recent / "ignored.tmp"
    for path in (old, new, skip):
        path.write_bytes(b"")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(new, (now, now))
    monkeypatch.setenv("APPDATA", str(tmp_path))

    names = context_fetcher._fetch_recent_files_win(max_files=5)

    # Fake .lnk files resolve to no target, so basenames are reported.
    assert names == ["newest.txt", "older.txt"]
    assert context_fetcher._fetch_recent_files_win(max_files=1) == ["newest.txt"]


def test_fetch_recent_files_win_without_recent_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "missing"))
    assert context_fetcher._fetch_recent_files_win() == []


def test_fetch_recent_files_linux_reads_xbel(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    first = docs / "first.txt"
    second = docs / "second.txt"
    gone = docs / "deleted.txt"
    first.write_text("x", encoding="utf-8")
    second.write_text("x", encoding="utf-8")
    xbel_dir = tmp_path / ".local" / "share"
    xbel_dir.mkdir(parents=True)
    (xbel_dir / "recently-used.xbel").write_text(
        f"""<?xml version="1.0"?>
<xbel version="1.0">
  <bookmark href="{_xbel_uri(first)}" visited="2026-07-01T10:00:00Z"/>
  <bookmark href="{_xbel_uri(second)}" visited="2026-07-02T10:00:00Z"/>
  <bookmark href="{_xbel_uri(gone)}" visited="2026-07-03T10:00:00Z"/>
  <bookmark href="https://example.com" visited="2026-07-04T10:00:00Z"/>
</xbel>
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    names = context_fetcher._fetch_recent_files_linux(max_files=5)

    # Newest first, deleted files and non-file bookmarks dropped. Paths come
    # back exactly as the xbel recorded them (forward slashes on every OS).
    assert names == [_xbel_uri(second)[7:], _xbel_uri(first)[7:]]
    assert context_fetcher._fetch_recent_files_linux(max_files=1) == [_xbel_uri(second)[7:]]


def test_fetch_recent_files_linux_without_xbel(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert context_fetcher._fetch_recent_files_linux() == []


def test_fetch_recent_files_dispatches_per_platform(monkeypatch):
    monkeypatch.setattr(context_fetcher, "_fetch_recent_files_win", lambda max_files=10: ["win"])
    monkeypatch.setattr(context_fetcher, "_fetch_recent_files_linux", lambda max_files=10: ["linux"])

    monkeypatch.setattr(context_fetcher, "_IS_WIN", True)
    assert context_fetcher._fetch_recent_files() == ["win"]
    monkeypatch.setattr(context_fetcher, "_IS_WIN", False)
    assert context_fetcher._fetch_recent_files() == ["linux"]


# ---------------------------------------------------------------------------
# Online search tool
# ---------------------------------------------------------------------------


def test_search_online_for_tool_uses_public_search(monkeypatch):
    rows = [{"title": "T", "url": "https://example.com", "snippet": "Current result"}]
    calls = []
    monkeypatch.setattr("core.web_search.search_web", lambda query, count: calls.append((query, count)) or rows)
    assert context_fetcher.search_online_for_tool("weather", 3) == rows
    assert calls == [("weather", 3)]


def test_search_failure_does_not_discard_other_ambient_context(monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise context_fetcher.WebSearchError("All public engines are unavailable")

    monkeypatch.setattr("core.web_search.search_web", fail)
    assert context_fetcher._search_online("weather") == []
    assert "All public engines are unavailable" in capsys.readouterr().out
    with pytest.raises(context_fetcher.WebSearchError):
        context_fetcher.search_online_for_tool("weather")
