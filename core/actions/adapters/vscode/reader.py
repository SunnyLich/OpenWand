"""Read one saved VS Code selection without controlling the editor UI."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from core.actions.adapters.vscode.snapshot import VSCodeSnapshot

_VSCODE_PROCESS_NAMES = {
    "code.exe",
    "code",
    "code - insiders.exe",
    "code-insiders",
    "cursor.exe",
    "cursor",
    "windsurf.exe",
    "windsurf",
}
_CODE_EDITOR_PROCESS_NAMES = {
    # JetBrains IDEs and Android Studio.
    "pycharm64.exe": "PyCharm", "pycharm.exe": "PyCharm", "pycharm": "PyCharm",
    "idea64.exe": "IntelliJ IDEA", "idea.exe": "IntelliJ IDEA", "idea": "IntelliJ IDEA",
    "webstorm64.exe": "WebStorm", "webstorm.exe": "WebStorm", "webstorm": "WebStorm",
    "goland64.exe": "GoLand", "goland.exe": "GoLand", "goland": "GoLand",
    "clion64.exe": "CLion", "clion.exe": "CLion", "clion": "CLion",
    "rider64.exe": "Rider", "rider.exe": "Rider", "rider": "Rider",
    "rubymine64.exe": "RubyMine", "rubymine.exe": "RubyMine", "rubymine": "RubyMine",
    "phpstorm64.exe": "PhpStorm", "phpstorm.exe": "PhpStorm", "phpstorm": "PhpStorm",
    "datagrip64.exe": "DataGrip", "datagrip.exe": "DataGrip", "datagrip": "DataGrip",
    "studio64.exe": "Android Studio", "studio.exe": "Android Studio", "studio": "Android Studio",
    # Other common desktop code editors and IDEs.
    "devenv.exe": "Visual Studio", "devenv": "Visual Studio",
    "eclipse.exe": "Eclipse", "eclipse": "Eclipse",
    "sublime_text.exe": "Sublime Text", "sublime_text": "Sublime Text",
    "zed.exe": "Zed", "zed": "Zed",
    "notepad++.exe": "Notepad++", "notepad++": "Notepad++",
    "gvim.exe": "GVim", "gvim": "GVim",
    "nvim.exe": "Neovim", "nvim": "Neovim",
    "vim.exe": "Vim", "vim": "Vim",
    "emacs.exe": "Emacs", "emacs": "Emacs",
    "kate": "Kate", "kwrite": "KWrite",
}
_CODE_EDITOR_TITLE_NAMES = {
    "pycharm": "PyCharm",
    "intellij idea": "IntelliJ IDEA",
    "webstorm": "WebStorm",
    "goland": "GoLand",
    "clion": "CLion",
    "rider": "Rider",
    "rubymine": "RubyMine",
    "phpstorm": "PhpStorm",
    "datagrip": "DataGrip",
    "android studio": "Android Studio",
    "microsoft visual studio": "Visual Studio",
    "eclipse ide": "Eclipse",
    "sublime text": "Sublime Text",
    "notepad++": "Notepad++",
    "neovim": "Neovim",
    "gnu emacs": "Emacs",
}
_MAX_FILE_BYTES = 200_000
_MAX_SELECTION_CHARS = 8_000


def is_vscode_app(active_app: dict[str, Any] | None) -> bool:
    """Return whether a captured window belongs to VS Code or a compatible fork."""
    app = active_app if isinstance(active_app, dict) else {}
    process_name = str(app.get("process_name") or "").strip().casefold()
    if process_name in _VSCODE_PROCESS_NAMES:
        return True
    title = str(app.get("name") or "").casefold()
    return any(marker in title for marker in ("visual studio code", " - cursor", " - windsurf"))


def code_editor_name(active_app: dict[str, Any] | None) -> str:
    """Return the product name for a supported saved-file code editor."""
    app = active_app if isinstance(active_app, dict) else {}
    if is_vscode_app(app):
        process = str(app.get("process_name") or "").casefold()
        if "cursor" in process or "cursor" in str(app.get("name") or "").casefold():
            return "Cursor"
        if "windsurf" in process or "windsurf" in str(app.get("name") or "").casefold():
            return "Windsurf"
        return "VS Code Insiders" if "insider" in process else "VS Code"
    process = str(app.get("process_name") or "").strip().casefold()
    if process in _CODE_EDITOR_PROCESS_NAMES:
        return _CODE_EDITOR_PROCESS_NAMES[process]
    title = str(app.get("name") or app.get("title") or "").casefold()
    if "visual studio code" in title:
        return "VS Code"
    return next((name for marker, name in _CODE_EDITOR_TITLE_NAMES.items() if marker in title), "Code editor")


def is_code_editor_app(active_app: dict[str, Any] | None) -> bool:
    """Return whether OpenWand can attempt an exact saved-file editor action."""
    app = active_app if isinstance(active_app, dict) else {}
    if is_vscode_app(app):
        return True
    process = str(app.get("process_name") or "").strip().casefold()
    if process in _CODE_EDITOR_PROCESS_NAMES:
        return True
    title = str(app.get("name") or app.get("title") or "").casefold()
    return any(marker in title for marker in _CODE_EDITOR_TITLE_NAMES)


class VSCodeSelectionReader:
    """Resolve and fingerprint the exact saved file containing a selection."""

    def inspect_selection(self, active_app: dict[str, Any], selected_text: str) -> VSCodeSnapshot:
        if not is_code_editor_app(active_app):
            raise ValueError("The recorded window is not a supported code editor.")
        if _title_looks_modified(str(active_app.get("name") or "")):
            raise ValueError("Save the active code editor file before asking OpenWand to change it.")
        if not str(selected_text or "").strip():
            raise ValueError("Select the code you want OpenWand to change, then try again.")
        if len(selected_text) > _MAX_SELECTION_CHARS:
            raise ValueError("The first code editor action supports selections up to 8,000 characters.")

        path = self._resolve_path(active_app)
        if not path:
            raise ValueError("OpenWand could not resolve the active editor tab to a saved file.")
        file_path = Path(path)
        if file_path.is_symlink():
            raise ValueError("OpenWand does not edit symlinked files in the first code editor action.")
        raw = file_path.read_bytes()
        if len(raw) > _MAX_FILE_BYTES:
            raise ValueError("The first code editor action supports saved files up to 200 KB.")
        if b"\x00" in raw:
            raise ValueError("The active editor tab is not a UTF-8 text file.")
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The first code editor action supports UTF-8 files only.") from exc

        matched = self._match_selection(text, selected_text)
        start = text.find(matched)
        if start < 0 or text.find(matched, start + 1) >= 0:
            raise ValueError(
                "The selected code appears more than once in the saved file. "
                "Select a larger unique block before applying a fix."
            )
        end = start + len(matched)
        return VSCodeSnapshot(
            file_path=str(file_path.resolve()),
            display_name=file_path.name,
            window_id=int(active_app.get("window_id") or 0),
            pid=int(active_app.get("pid") or 0),
            text=text,
            selected_text=matched,
            selection_start=start,
            selection_end=end,
            fingerprint=hashlib.sha256(raw).hexdigest(),
            selection_fingerprint=_text_fingerprint(matched),
            has_utf8_bom=has_bom,
            editor_name=code_editor_name(active_app),
        )

    def inspect_empty_file(self, active_app: dict[str, Any]) -> VSCodeSnapshot:
        """Capture an active saved empty UTF-8 file for a whole-file insertion."""
        if not is_code_editor_app(active_app):
            raise ValueError("The recorded window is not a supported code editor.")
        if _title_looks_modified(str(active_app.get("name") or "")):
            raise ValueError("Save the active VS Code file before asking OpenWand to change it.")
        path = self._resolve_path(active_app)
        if not path:
            raise ValueError(
                "This VS Code tab is unsaved. Save it once so OpenWand can edit it without taking focus."
            )
        file_path = Path(path)
        if file_path.is_symlink():
            raise ValueError("OpenWand does not edit symlinked files in the first VS Code action.")
        raw = file_path.read_bytes()
        if len(raw) > _MAX_FILE_BYTES or b"\x00" in raw:
            raise ValueError("The active VS Code tab is not a supported UTF-8 text file.")
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The first VS Code action supports UTF-8 files only.") from exc
        if text:
            raise ValueError("Select a unique code block before asking OpenWand to change a non-empty file.")
        empty_hash = _text_fingerprint("")
        return VSCodeSnapshot(
            file_path=str(file_path.resolve()),
            display_name=file_path.name,
            window_id=int(active_app.get("window_id") or 0),
            pid=int(active_app.get("pid") or 0),
            text="",
            selected_text="",
            selection_start=0,
            selection_end=0,
            fingerprint=hashlib.sha256(raw).hexdigest(),
            selection_fingerprint=empty_hash,
            has_utf8_bom=has_bom,
            is_whole_file=True,
            editor_name=code_editor_name(active_app),
        )

    @staticmethod
    def _resolve_path(active_app: dict[str, Any]) -> str:
        explicit = str(active_app.get("document_path") or "").strip()
        if explicit and os.path.isfile(explicit):
            return explicit
        from core.context_fetcher import WindowInfo, get_active_document_path

        resolved = get_active_document_path(
            active_window=WindowInfo(
                title=str(active_app.get("name") or ""),
                process_name=str(active_app.get("process_name") or ""),
                pid=int(active_app.get("pid") or 0),
                hwnd=int(active_app.get("window_id") or 0),
            )
        )
        resolved_path = Path(str(resolved or "")).expanduser()
        if resolved_path.is_absolute() and resolved_path.is_file():
            return str(resolved_path)

        # A newly saved loose file is not always committed to VS Code's recent
        # workspace metadata immediately. Check only direct, standard user
        # folders and require one unambiguous exact filename match.
        filename = _filename_from_window(str(active_app.get("name") or ""))
        if not filename:
            return ""
        user_root = Path(os.environ.get("USERPROFILE") or Path.home())
        roots = [user_root / "Desktop", user_root / "Documents", user_root / "Downloads"]
        onedrive = str(os.environ.get("OneDrive") or "").strip()
        if onedrive:
            roots.extend((Path(onedrive) / "Desktop", Path(onedrive) / "Documents"))
        matches = {
            str(candidate.resolve())
            for candidate in (root / filename for root in roots)
            if candidate.is_file()
        }
        return next(iter(matches)) if len(matches) == 1 else ""

    @staticmethod
    def _match_selection(text: str, selected_text: str) -> str:
        candidates = [str(selected_text)]
        if "\r\n" in text:
            candidates.append(str(selected_text).replace("\r\n", "\n").replace("\n", "\r\n"))
        else:
            candidates.append(str(selected_text).replace("\r\n", "\n"))
        for candidate in dict.fromkeys(candidates):
            if candidate and candidate in text:
                return candidate
        raise ValueError("The selected code no longer matches the saved file.")


def _text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _filename_from_window(title: str) -> str:
    clean = str(title or "").strip().lstrip("\u25cf\u2022*").strip()
    for marker in (
        " - Visual Studio Code - Insiders",
        " - Visual Studio Code",
        " - Cursor",
        " - Windsurf",
    ):
        if marker in clean:
            clean = clean.split(marker, 1)[0].strip()
            break
    if " - " in clean:
        clean = clean.split(" - ", 1)[0].strip()
    return Path(clean).name if clean else ""


def _title_looks_modified(title: str) -> bool:
    """Recognize common dirty-tab markers without guessing from app focus."""
    text = str(title or "").strip()
    return text.startswith(("\u25cf", "\u2022", "*")) or bool(
        re.search(r"\*(?:\s*(?:-|\u2013|\u2014)|$)", text)
    )
