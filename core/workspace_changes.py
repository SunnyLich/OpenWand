"""Host-owned capture and restoration for files changed by agent harnesses."""
from __future__ import annotations

import difflib
import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

_MAX_BACKUP_BYTES = 20 * 1024 * 1024
_MAX_DIFF_CHARS = 200_000


def _digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _safe_target(root: Path, value: object) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved


def _line_counts(diff: str) -> tuple[int, int]:
    added = sum(1 for line in diff.splitlines() if line.startswith("+") and not line.startswith("+++"))
    deleted = sum(1 for line in diff.splitlines() if line.startswith("-") and not line.startswith("---"))
    return added, deleted


def _generated_diff(item: dict[str, Any], target: Path) -> str:
    try:
        before = (
            Path(str(item.get("before_backup") or "")).read_bytes()
            if item.get("before_exists")
            else b""
        )
        after = target.read_bytes() if target.is_file() else b""
    except OSError:
        return ""
    if b"\x00" in before or b"\x00" in after:
        return ""
    before_text = before.decode("utf-8", errors="replace").splitlines()
    after_text = after.decode("utf-8", errors="replace").splitlines()
    path = str(item.get("path") or "file")
    return "\n".join(
        difflib.unified_diff(
            before_text,
            after_text,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )


class WorkspaceChangeRecorder:
    """Capture first preimages and final file states for one harness turn."""

    def __init__(self, root: str | Path, storage_dir: str | Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        if storage_dir is None:
            from core.system.paths import USER_DATA_DIR

            storage_dir = USER_DATA_DIR / "workspace_change_backups"
        self.storage_dir = Path(storage_dir).expanduser().resolve() / uuid.uuid4().hex
        self._items: dict[str, dict[str, Any]] = {}

    def capture(self, path: object, *, diff: object = "") -> None:
        target = _safe_target(self.root, path)
        if target is None:
            return
        key = os.path.normcase(str(target))
        item = self._items.get(key)
        if item is None:
            before_exists = target.is_file()
            backup = ""
            restorable = True
            if before_exists:
                try:
                    if target.stat().st_size > _MAX_BACKUP_BYTES:
                        restorable = False
                    else:
                        self.storage_dir.mkdir(parents=True, exist_ok=True)
                        backup_path = self.storage_dir / f"{len(self._items):04d}.before"
                        shutil.copyfile(target, backup_path)
                        backup = str(backup_path)
                except OSError:
                    restorable = False
            try:
                relative = target.relative_to(self.root).as_posix()
            except ValueError:
                return
            item = {
                "path": relative,
                "absolute_path": str(target),
                "before_exists": before_exists,
                "before_backup": backup,
                "restorable": restorable,
                "diff_parts": [],
            }
            self._items[key] = item
        diff_text = str(diff or "")
        if diff_text and diff_text not in item["diff_parts"]:
            item["diff_parts"].append(diff_text)

    def capture_changes(self, changes: object) -> None:
        for raw in changes if isinstance(changes, list) else []:
            if isinstance(raw, dict):
                self.capture(raw.get("path"), diff=raw.get("diff"))

    def finish(self) -> dict[str, Any]:
        files: list[dict[str, Any]] = []
        combined_diff: list[str] = []
        for item in self._items.values():
            target = Path(item["absolute_path"])
            after_exists = target.is_file()
            before_exists = bool(item["before_exists"])
            before_hash = ""
            if before_exists and item.get("before_backup"):
                try:
                    before_hash = _digest(Path(item["before_backup"]))
                except OSError:
                    item["restorable"] = False
            after_hash = ""
            if after_exists:
                try:
                    after_hash = _digest(target)
                except OSError:
                    continue
            if before_exists == after_exists and before_hash and before_hash == after_hash:
                continue
            if not before_exists and not after_exists:
                continue
            diff = "\n".join(str(part) for part in item.pop("diff_parts", []) if str(part).strip())
            if not diff:
                diff = _generated_diff(item, target)
            diff = diff[:_MAX_DIFF_CHARS]
            added, deleted = _line_counts(diff)
            item.update(
                {
                    "after_exists": after_exists,
                    "after_sha256": after_hash,
                    "added": added,
                    "deleted": deleted,
                    "diff": diff,
                    "kind": "added" if not before_exists else "deleted" if not after_exists else "modified",
                }
            )
            files.append(item)
            if diff:
                combined_diff.append(diff)
        if not files:
            shutil.rmtree(self.storage_dir, ignore_errors=True)
            return {}
        return {
            "version": 1,
            "source": "harness_file_events",
            "root": str(self.root),
            "files": files,
            "diff": "\n\n".join(combined_diff)[:_MAX_DIFF_CHARS],
            "restored": False,
        }


def restore_workspace_changes(change_set: dict[str, Any]) -> dict[str, Any]:
    """Restore a recorded set only if no file changed again afterwards."""
    try:
        root = Path(str(change_set.get("root") or "")).expanduser().resolve()
    except OSError:
        return {"ok": False, "error": "The recorded workspace is unavailable."}
    files = [item for item in change_set.get("files", []) if isinstance(item, dict)]
    if not files:
        return {"ok": False, "error": "There are no recorded file changes to restore."}
    prepared: list[tuple[dict[str, Any], Path]] = []
    for item in files:
        target = _safe_target(root, item.get("absolute_path") or item.get("path"))
        if target is None or not bool(item.get("restorable", True)):
            return {"ok": False, "error": f"{item.get('path') or 'A file'} cannot be safely restored."}
        after_exists = bool(item.get("after_exists"))
        if target.is_file() != after_exists:
            return {"ok": False, "error": f"{item.get('path')} changed again after this reply."}
        if bool(item.get("before_exists")) and not Path(
            str(item.get("before_backup") or "")
        ).is_file():
            return {"ok": False, "error": f"The backup for {item.get('path')} is unavailable."}
        if after_exists:
            try:
                if _digest(target) != str(item.get("after_sha256") or ""):
                    return {"ok": False, "error": f"{item.get('path')} changed again after this reply."}
            except OSError:
                return {"ok": False, "error": f"{item.get('path')} could not be verified."}
        prepared.append((item, target))
    for item, target in prepared:
        if bool(item.get("before_exists")):
            backup = Path(str(item.get("before_backup") or ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.openwand-restore-{uuid.uuid4().hex}.tmp")
            shutil.copyfile(backup, temporary)
            os.replace(temporary, target)
        elif target.exists():
            target.unlink()
    change_set["restored"] = True
    return {"ok": True, "restored": len(prepared)}
