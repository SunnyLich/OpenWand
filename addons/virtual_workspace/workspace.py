"""Isolated file-workspace state for the Virtual Workspace addon.

The controller intentionally exposes a small typed surface.  It never accepts
an absolute host path or follows a workspace symlink. User-invoked Explorer
operations remain scoped to the session and deletion moves entries to a
session-local recovery folder instead of erasing them.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
import stat
import threading
import time
from collections import deque
from pathlib import Path, PurePosixPath
from typing import Any

MAX_TEXT_BYTES = 256 * 1024
MAX_PREVIEW_BYTES = 12 * 1024 * 1024
MAX_ENTRIES = 500
MAX_PATH_LENGTH = 240
MAX_PATH_DEPTH = 12


class WorkspaceError(RuntimeError):
    """A safe, user-facing workspace error."""


class WorkspaceController:
    """Own one virtual workspace session and its activity journal."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data_dir: Path | None = None
        self._session_id = ""
        self._root: Path | None = None
        self._status = "idle"
        self._paused = False
        self._control_owner = "openwand"
        self._started_at = 0.0
        self._updated_at = time.time()
        self._operations: deque[dict[str, Any]] = deque(maxlen=2_000)
        self._cursor: dict[str, Any] = {"visible": False, "path": "", "label": "", "kind": ""}
        self._observed_entries: dict[str, tuple[str, int, int]] = {}
        self._agent_changes: dict[str, str] = {}
        self._task_active = False
        self._viewer: Any = None

    def configure(self, data_dir: Path) -> None:
        """Set the per-addon data directory supplied by OpenWand."""
        path = Path(data_dir).resolve()
        with self._lock:
            if self._status == "running" and self._data_dir != path:
                raise WorkspaceError("Cannot move a running workspace.")
            self._data_dir = path

    def start(self, label: str = "OpenWand Workspace") -> dict[str, Any]:
        """Start a session and its local viewer, or return the running session."""
        with self._lock:
            if self._status == "running":
                return self.status()
            if self._data_dir is None:
                raise WorkspaceError("The addon has not finished starting.")

            session_id = secrets.token_hex(8)
            root = (self._data_dir / "sessions" / session_id / "files").resolve()
            root.mkdir(parents=True, exist_ok=False)
            self._session_id = session_id
            self._root = root
            self._status = "running"
            self._paused = False
            self._control_owner = "openwand"
            self._started_at = time.time()
            self._updated_at = self._started_at
            self._operations.clear()
            self._cursor = {"visible": False, "path": "", "label": "", "kind": ""}
            self._observed_entries = {}
            self._agent_changes = {}
            self._task_active = False
            self._record("session", "Workspace started", label=label)

            from .viewer import ViewerServer

            viewer = ViewerServer(
                self.snapshot,
                self.apply_viewer_control,
                self.read_text,
                self.read_preview,
                self.check_file,
                self.task_scope,
                self.record_client_event,
                self.save_user_text,
                self.apply_user_file_operation,
            )
            try:
                viewer.start()
            except Exception:
                self._status = "error"
                raise
            self._viewer = viewer
            return self.status()

    def stop(self) -> dict[str, Any]:
        """Stop viewing and freeze the current session without deleting its files."""
        viewer = None
        with self._lock:
            if self._status == "running":
                self._record("session", "Workspace stopped")
                self._status = "stopped"
                self._paused = True
                self._control_owner = "user"
                self._task_active = False
            viewer, self._viewer = self._viewer, None
        if viewer is not None:
            viewer.stop()
        return self.status()

    def pause(self, *, owner: str = "user") -> dict[str, Any]:
        """Pause model mutations and hand control to the user."""
        with self._lock:
            self._require_running()
            if not self._paused or self._control_owner != owner:
                self._paused = True
                self._control_owner = owner
                self._record("control", "OpenWand paused", owner=owner)
            return self.status()

    def resume(self) -> dict[str, Any]:
        """Return mutation control to OpenWand."""
        with self._lock:
            self._require_running()
            if self._paused or self._control_owner != "openwand":
                self._paused = False
                self._control_owner = "openwand"
                self._record("control", "OpenWand resumed", owner="openwand")
            return self.status()

    def apply_viewer_control(self, action: str) -> dict[str, Any]:
        """Handle the viewer's deliberately tiny control surface."""
        if action in {"pause", "take_control"}:
            return self.pause(owner="user")
        if action == "resume":
            return self.resume()
        if action == "task_started":
            with self._lock:
                self._require_running()
                self._task_active = True
                self._record("task", "Agent task started in the virtual desktop")
                return self.status()
        if action == "task_finished":
            with self._lock:
                self._sync_external_activity(self.list_entries())
                self._task_active = False
                self._paused = False
                self._control_owner = "openwand"
                self._cursor = {"visible": False, "path": "", "label": "", "kind": ""}
                self._record("task", "Agent task finished")
                return self.status()
        raise WorkspaceError("Unknown control action.")

    def create_folder(self, relative_path: str) -> dict[str, Any]:
        """Create one folder under an existing workspace parent."""
        with self._lock:
            self._require_mutation_control()
            target, display = self._safe_target(relative_path)
            self._require_clean_parent(target)
            if target.exists() or target.is_symlink():
                raise WorkspaceError(f"Already exists: {display}")
            target.mkdir()
            self._record("folder", f"Created folder {display}", path=display)
            self._hide_cursor()
            self._remember_current_entries()
            return {"ok": True, "path": display, "kind": "folder"}

    def write_text(self, relative_path: str, text: str) -> dict[str, Any]:
        """Create a UTF-8 text file; existing files are never overwritten."""
        payload = str(text).encode("utf-8")
        if len(payload) > MAX_TEXT_BYTES:
            raise WorkspaceError(f"Text is larger than {MAX_TEXT_BYTES // 1024} KB.")
        with self._lock:
            self._require_mutation_control()
            target, display = self._safe_target(relative_path)
            self._require_clean_parent(target)
            if target.exists() or target.is_symlink():
                raise WorkspaceError(f"Refusing to overwrite: {display}")
            try:
                with target.open("xb") as handle:
                    handle.write(payload)
            except FileExistsError as exc:
                raise WorkspaceError(f"Refusing to overwrite: {display}") from exc
            self._record("file", f"Created file {display}", path=display, bytes=len(payload))
            self._point_cursor(display, kind="text")
            self._remember_current_entries()
            return {"ok": True, "path": display, "kind": "file", "bytes": len(payload)}

    def list_entries(self) -> list[dict[str, Any]]:
        """Return bounded metadata for workspace files without reading contents."""
        with self._lock:
            root = self._root
            if root is None or not root.exists():
                return []
            entries: list[dict[str, Any]] = []
            for current, dirs, files in os.walk(root, followlinks=False):
                dirs.sort(key=str.casefold)
                files.sort(key=str.casefold)
                current_path = Path(current)
                safe_dirs: list[str] = []
                for name in dirs:
                    item = current_path / name
                    relative = item.relative_to(root).as_posix()
                    if item.is_symlink():
                        entries.append({"path": relative, "name": name, "kind": "link", "modified_ns": 0})
                    else:
                        safe_dirs.append(name)
                        entries.append({
                            "path": relative,
                            "name": name,
                            "kind": "folder",
                            "modified_ns": item.stat().st_mtime_ns,
                        })
                    if len(entries) >= MAX_ENTRIES:
                        return entries
                dirs[:] = safe_dirs
                for name in files:
                    item = current_path / name
                    relative = item.relative_to(root).as_posix()
                    kind = "link" if item.is_symlink() else "file"
                    size = 0 if kind == "link" else item.stat().st_size
                    entries.append({
                        "path": relative,
                        "name": name,
                        "kind": kind,
                        "bytes": size,
                        "modified_ns": 0 if kind == "link" else item.stat().st_mtime_ns,
                        **({} if kind == "link" else self._preview_metadata(relative)),
                    })
                    if len(entries) >= MAX_ENTRIES:
                        return entries
            return entries

    def status(self) -> dict[str, Any]:
        """Return non-secret session status for tools and tray actions."""
        with self._lock:
            return {
                "ok": self._status in {"running", "stopped"},
                "status": self._status,
                "session_id": self._session_id,
                "paused": self._paused,
                "control_owner": self._control_owner,
                "entry_count": len(self.list_entries()),
                "viewer_running": self._viewer is not None,
            }

    def snapshot(self) -> dict[str, Any]:
        """Return the complete, non-secret state rendered by the local viewer."""
        with self._lock:
            entries = self.list_entries()
            self._sync_external_activity(entries)
            return {
                **self.status(),
                "started_at": self._started_at,
                "updated_at": self._updated_at,
                "entries": entries,
                "operations": list(self._operations),
                "changes": dict(self._agent_changes),
                "cursor": dict(self._cursor),
                "task_active": self._task_active,
                "capabilities": {
                    "view_files": True,
                    "preview_files": True,
                    "preview_max_bytes": MAX_PREVIEW_BYTES,
                    "pause": True,
                    "take_control": True,
                    "remote_input": False,
                    "virtual_input": True,
                    "host_file_access": False,
                    "user_file_operations": True,
                    "recoverable_delete": True,
                },
            }

    def read_text(self, relative_path: str) -> dict[str, Any]:
        """Read one bounded UTF-8 file for the native virtual editor."""
        with self._lock:
            self._require_running()
            target, display = self._safe_target(relative_path)
            payload, truncated = self._read_regular_file(target, MAX_TEXT_BYTES, truncate=True)
            text = payload.decode("utf-8", errors="replace")
            return {"ok": True, "path": display, "text": text, "truncated": truncated}

    def read_preview(self, relative_path: str) -> dict[str, Any]:
        """Return one bounded workspace file for an authenticated native preview.

        The payload is Base64 because the bridge uses JSON.  No path, URL, or
        host-file handle is exposed to the renderer.  Files over the fixed
        preview ceiling are rejected instead of returning a corrupt partial
        image or PDF.
        """
        with self._lock:
            self._require_running()
            target, display = self._safe_target(relative_path)
            payload, _truncated = self._read_regular_file(
                target,
                MAX_PREVIEW_BYTES,
                truncate=False,
            )
            metadata = self._preview_metadata(display, payload[:16])
            modified_ns = target.stat().st_mtime_ns
            return {
                "ok": True,
                "path": display,
                "name": PurePosixPath(display).name,
                **metadata,
                "bytes": len(payload),
                "modified_ns": modified_ns,
                "encoding": "base64",
                "data_base64": base64.b64encode(payload).decode("ascii"),
            }

    def save_user_text(
        self,
        relative_path: str,
        text: str,
        expected_modified_ns: int,
    ) -> dict[str, Any]:
        """Optimistically save a user's edit without silently overwriting OpenWand."""
        payload = str(text).encode("utf-8")
        if len(payload) > MAX_TEXT_BYTES:
            raise WorkspaceError(f"Text is larger than {MAX_TEXT_BYTES // 1024} KB.")
        with self._lock:
            self._require_running()
            target, display = self._safe_target(relative_path)
            if target.is_symlink() or not target.exists():
                raise WorkspaceError(f"File no longer exists: {display}")
            before = target.stat()
            if not stat.S_ISREG(before.st_mode):
                raise WorkspaceError(f"Not a regular file: {display}")
            expected = int(expected_modified_ns or 0)
            if expected <= 0 or before.st_mtime_ns != expected:
                raise WorkspaceError(
                    "This file changed after you opened it. Your text is still in the editor; "
                    "review OpenWand's newer version before saving again."
                )
            temporary = target.with_name(f".{target.name}.openwand-user-{secrets.token_hex(5)}.tmp")
            try:
                with temporary.open("xb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                latest = target.stat()
                if latest.st_mtime_ns != before.st_mtime_ns:
                    raise WorkspaceError(
                        "OpenWand changed this file while your save was being prepared. "
                        "Your text is still in the editor."
                    )
                os.replace(temporary, target)
            finally:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            modified_ns = target.stat().st_mtime_ns
            self._record(
                "user_file",
                f"You edited file {display}",
                path=display,
                bytes=len(payload),
                actor="user",
            )
            self._hide_cursor()
            self._remember_current_entries()
            return {
                "ok": True,
                "path": display,
                "bytes": len(payload),
                "modified_ns": modified_ns,
            }

    def apply_user_file_operation(
        self,
        action: str,
        relative_path: str = "",
        name: str = "",
        kind: str = "file",
    ) -> dict[str, Any]:
        """Apply one user-requested Explorer operation inside this session."""
        operation = str(action or "").strip().lower()
        with self._lock:
            self._require_running()
            if operation == "create":
                parent_display = ""
                parent = self._root
                if relative_path:
                    parent, parent_display = self._safe_target(relative_path)
                    if parent.is_symlink() or not parent.is_dir():
                        raise WorkspaceError("Choose a regular workspace folder.")
                assert parent is not None
                clean_name = self._safe_entry_name(name)
                display = f"{parent_display}/{clean_name}" if parent_display else clean_name
                target, display = self._safe_target(display)
                self._require_clean_parent(target)
                if target.exists() or target.is_symlink():
                    raise WorkspaceError(f"Already exists: {display}")
                if str(kind or "file").strip().lower() == "folder":
                    target.mkdir()
                    entry_kind = "folder"
                else:
                    with target.open("xb"):
                        pass
                    entry_kind = "file"
                self._agent_changes.pop(display, None)
                self._record(
                    "user_file",
                    f"You created {entry_kind} {display}",
                    path=display,
                    actor="user",
                )
                self._hide_cursor()
                self._remember_current_entries()
                return {"ok": True, "action": operation, "path": display, "kind": entry_kind}

            target, display = self._safe_target(relative_path)
            self._require_clean_parent(target)
            if target.is_symlink() or not target.exists():
                raise WorkspaceError(f"No longer exists: {display}")

            if operation == "rename":
                clean_name = self._safe_entry_name(name)
                destination_display = (
                    PurePosixPath(display).parent / clean_name
                ).as_posix()
                if destination_display == f"./{clean_name}":
                    destination_display = clean_name
                destination, destination_display = self._safe_target(destination_display)
                self._require_clean_parent(destination)
                if destination.exists() or destination.is_symlink():
                    raise WorkspaceError(f"Already exists: {destination_display}")
                target.rename(destination)
                self._agent_changes.pop(display, None)
                self._agent_changes.pop(destination_display, None)
                self._record(
                    "user_file",
                    f"You renamed {display} to {destination_display}",
                    path=destination_display,
                    previous_path=display,
                    actor="user",
                )
                self._hide_cursor()
                self._remember_current_entries()
                return {
                    "ok": True,
                    "action": operation,
                    "path": destination_display,
                    "previous_path": display,
                    "kind": "folder" if destination.is_dir() else "file",
                }

            if operation == "delete":
                root = self._root
                assert root is not None
                trash = root.parent / "user-trash"
                trash.mkdir(exist_ok=True)
                recovery_name = f"{secrets.token_hex(6)}-{target.name}"
                recovery_target = trash / recovery_name
                target.rename(recovery_target)
                self._agent_changes.pop(display, None)
                self._record(
                    "user_file",
                    f"You moved {display} to workspace trash",
                    path=display,
                    actor="user",
                    recoverable=True,
                    recovery_name=recovery_name,
                )
                self._hide_cursor()
                self._remember_current_entries()
                return {
                    "ok": True,
                    "action": operation,
                    "path": display,
                    "recoverable": True,
                }

        raise WorkspaceError("Unknown file operation.")

    def check_file(self, relative_path: str) -> dict[str, Any]:
        """Run one fixed, non-executing syntax/data check in the background process."""
        from .background_runner import CheckRequest, LimitedCheck, LimitedWorkspaceRunner

        with self._lock:
            self._require_running()
            _target, display = self._safe_target(relative_path)
            root = self._root
        if root is None:  # pragma: no cover - guarded by _require_running
            raise WorkspaceError("Workspace is not running.")
        suffix = PurePosixPath(display).suffix.casefold()
        check = {
            ".py": LimitedCheck.PYTHON_SYNTAX,
            ".pyi": LimitedCheck.PYTHON_SYNTAX,
            ".js": LimitedCheck.JAVASCRIPT_SYNTAX,
            ".cjs": LimitedCheck.JAVASCRIPT_SYNTAX,
            ".mjs": LimitedCheck.JAVASCRIPT_SYNTAX,
            ".json": LimitedCheck.JSON,
        }.get(suffix)
        if check is None:
            raise WorkspaceError("Automatic checks support Python, JavaScript, and JSON files.")
        return LimitedWorkspaceRunner(root).run(CheckRequest(check, (display,))).to_dict()

    def task_scope(self) -> dict[str, Any]:
        """Return the session root only through the dedicated authenticated route."""
        with self._lock:
            self._require_running()
            return {"ok": True, "scope_folder": str(self._root)}

    def record_client_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Persist one factual UI/agent progress event in the session journal."""
        with self._lock:
            self._require_running()
            message = str(payload.get("message") or "").replace("\x00", "").strip()[:1_000]
            if not message:
                raise WorkspaceError("Activity message is required.")
            kind = str(payload.get("kind") or "progress").strip().lower()[:40]
            event_id = str(payload.get("id") or secrets.token_hex(5)).strip()[:80]
            self._record(kind, message, id=event_id)
            return {"ok": True, "id": event_id}

    @property
    def viewer_url(self) -> str:
        """Return the secret-bearing local viewer URL for the trusted UI boundary only."""
        with self._lock:
            if self._viewer is None:
                raise WorkspaceError("The viewer is not running.")
            return str(self._viewer.url)

    def _require_running(self) -> None:
        if self._status != "running" or self._root is None:
            raise WorkspaceError("Start the virtual workspace first.")

    def _require_mutation_control(self) -> None:
        self._require_running()
        if self._paused or self._control_owner != "openwand":
            raise WorkspaceError("OpenWand is paused because you have control of this workspace.")

    def _safe_target(self, raw_path: str) -> tuple[Path, str]:
        root = self._root
        assert root is not None
        value = str(raw_path or "").strip().replace("\\", "/")
        if not value or len(value) > MAX_PATH_LENGTH or "\x00" in value:
            raise WorkspaceError("Use a short relative workspace path.")
        relative = PurePosixPath(value)
        if relative.is_absolute() or len(relative.parts) > MAX_PATH_DEPTH:
            raise WorkspaceError("Only relative paths inside the workspace are allowed.")
        if any(part in {"", ".", ".."} or ":" in part for part in relative.parts):
            raise WorkspaceError("That path is not allowed inside the workspace.")
        target = root.joinpath(*relative.parts)
        try:
            target.resolve(strict=False).relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceError("That path leaves the workspace.") from exc
        return target, relative.as_posix()

    @staticmethod
    def _safe_entry_name(raw_name: str) -> str:
        """Validate one Explorer-style file or folder name, not a path."""
        name = str(raw_name or "").strip()
        if (
            not name
            or len(name) > 120
            or name in {".", ".."}
            or any(char in name for char in "\x00\\/:*?\"<>|")
        ):
            raise WorkspaceError("Use a valid file or folder name.")
        return name

    def _require_clean_parent(self, target: Path) -> None:
        root = self._root
        assert root is not None
        parent = target.parent
        if not parent.is_dir():
            raise WorkspaceError("Create the parent folder first.")
        current = parent
        while current != root:
            if current.is_symlink():
                raise WorkspaceError("Workspace links cannot be used as destinations.")
            current = current.parent

    def _read_regular_file(
        self,
        target: Path,
        limit: int,
        *,
        truncate: bool,
    ) -> tuple[bytes, bool]:
        """Read a regular file while rejecting links in every path component."""
        root = self._root
        assert root is not None
        current = root
        relative_parts = target.relative_to(root).parts
        try:
            for part in relative_parts:
                current = current / part
                if current.is_symlink():
                    raise WorkspaceError("Workspace links cannot be opened.")
            before = target.stat(follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError, OSError) as exc:
            raise WorkspaceError("Only regular workspace files can be opened.") from exc
        if not stat.S_ISREG(before.st_mode):
            raise WorkspaceError("Only regular workspace files can be opened.")
        if not truncate and before.st_size > limit:
            raise WorkspaceError(f"Preview is larger than {limit // (1024 * 1024)} MB.")

        try:
            with target.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if not stat.S_ISREG(opened.st_mode):
                    raise WorkspaceError("Only regular workspace files can be opened.")
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                    raise WorkspaceError("Workspace file changed while it was being opened.")
                payload = handle.read(limit + 1)
        except WorkspaceError:
            raise
        except OSError as exc:
            raise WorkspaceError("Workspace file could not be opened.") from exc

        # Re-check the path after the read so a concurrent link swap cannot be
        # silently accepted.  The open descriptor above remains bounded either way.
        current = root
        for part in relative_parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("Workspace links cannot be opened.")
        if len(payload) > limit:
            if not truncate:
                raise WorkspaceError(f"Preview is larger than {limit // (1024 * 1024)} MB.")
            return payload[:limit], True
        return payload, False

    @staticmethod
    def _preview_metadata(path: str, prefix: bytes | None = None) -> dict[str, str]:
        """Describe how a native viewer may safely present a workspace file."""
        guessed, _encoding = mimetypes.guess_type(path, strict=False)
        mime_type = guessed or "application/octet-stream"
        preview_kind = "binary"
        if prefix is None:
            if mime_type.startswith("image/"):
                preview_kind = "image"
            elif mime_type == "application/pdf":
                preview_kind = "pdf"
            elif mime_type.startswith("text/") or mime_type in {
                "application/json",
                "application/xml",
                "application/javascript",
            }:
                preview_kind = "text"
            return {"mime_type": mime_type, "preview_kind": preview_kind}
        if prefix.startswith(b"%PDF-"):
            mime_type, preview_kind = "application/pdf", "pdf"
        elif prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            mime_type, preview_kind = "image/png", "image"
        elif prefix.startswith(b"\xff\xd8\xff"):
            mime_type, preview_kind = "image/jpeg", "image"
        elif prefix.startswith((b"GIF87a", b"GIF89a")):
            mime_type, preview_kind = "image/gif", "image"
        elif prefix.startswith(b"BM"):
            mime_type, preview_kind = "image/bmp", "image"
        elif prefix.startswith((b"II*\x00", b"MM\x00*")):
            mime_type, preview_kind = "image/tiff", "image"
        elif len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
            mime_type, preview_kind = "image/webp", "image"
        elif mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
            "application/javascript",
        }:
            preview_kind = "text"
        return {"mime_type": mime_type, "preview_kind": preview_kind}

    def _record(self, kind: str, message: str, **details: Any) -> None:
        now = time.time()
        self._updated_at = now
        event = {
            "id": secrets.token_hex(5),
            "kind": kind,
            "message": message,
            "time": now,
            **details,
        }
        self._operations.append(event)
        root = self._root
        if root is not None:
            try:
                journal = root.parent / "activity.jsonl"
                with journal.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
            except OSError:
                pass

    def _point_cursor(self, path: str, *, kind: str) -> None:
        label = "OpenWand agent" if kind == "text" else "OpenWand"
        self._cursor = {
            "visible": True,
            "path": path,
            "label": label,
            "kind": kind,
            "time": time.time(),
        }

    def _hide_cursor(self) -> None:
        self._cursor = {"visible": False, "path": "", "label": "", "kind": "", "time": time.time()}

    @staticmethod
    def _entry_versions(entries: list[dict[str, Any]]) -> dict[str, tuple[str, int, int]]:
        return {
            str(item.get("path") or ""): (
                str(item.get("kind") or ""),
                int(item.get("bytes") or 0),
                int(item.get("modified_ns") or 0),
            )
            for item in entries
            if isinstance(item, dict) and str(item.get("path") or "")
        }

    def _remember_current_entries(self) -> None:
        self._observed_entries = self._entry_versions(self.list_entries())

    def _sync_external_activity(self, entries: list[dict[str, Any]]) -> None:
        """Turn scoped-agent file changes into visible desktop activity."""
        current = self._entry_versions(entries)
        previous = self._observed_entries
        if current == previous:
            return
        for path in sorted(current.keys() - previous.keys()):
            kind = current[path][0]
            noun = "folder" if kind == "folder" else "file"
            actor = "OpenWand" if self._task_active else "Workspace"
            if self._task_active:
                self._agent_changes[path] = "created"
            self._record(kind, f"{actor} created {noun} {path}", path=path)
            if kind == "folder":
                self._hide_cursor()
            else:
                self._point_cursor(path, kind="text")
        for path in sorted(current.keys() & previous.keys()):
            if current[path] == previous[path] or current[path][0] != "file":
                continue
            actor = "OpenWand" if self._task_active else "Workspace"
            if self._task_active and self._agent_changes.get(path) != "created":
                self._agent_changes[path] = "edited"
            self._record("file", f"{actor} updated file {path}", path=path)
            self._point_cursor(path, kind="text")
        for path in sorted(previous.keys() - current.keys()):
            actor = "OpenWand" if self._task_active else "Workspace"
            if self._task_active:
                self._agent_changes[path] = "deleted"
            self._record("file", f"{actor} removed {path}", path=path)
        self._observed_entries = current
