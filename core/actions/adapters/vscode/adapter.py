"""Validate, apply, and verify saved-file actions for supported code editors."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any

from core.actions.adapters.vscode.capabilities import REPLACE_FILE, REPLACE_SELECTION, vscode_capabilities
from core.actions.adapters.vscode.preview import render_vscode_preview
from core.actions.adapters.vscode.reader import _title_looks_modified
from core.actions.adapters.vscode.snapshot import VSCodeSnapshot
from core.actions.contracts import (
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ActionRisk,
    ActionTarget,
    ValidationIssue,
)
from core.actions.errors import ActionValidationError
from core.actions.registry import ActionRegistry


class VSCodeActionAdapter:
    """Apply one confirmed replacement without driving an editor's keyboard or focus."""

    def __init__(self) -> None:
        self._idempotent_results: dict[str, ActionExecutionResult] = {}
        self._registry = ActionRegistry(self.capabilities())
        self.last_execution_timing: dict[str, float] = {}

    def capabilities(self):
        return vscode_capabilities()

    def validate(self, plan: ActionPlan, snapshot: VSCodeSnapshot) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = list(self._registry.validate_plan(plan))
        if not plan.plan_id.strip():
            issues.append(ValidationIssue("missing_plan_id", "The code editor action has no plan identity."))
        if plan.app != "vscode":
            issues.append(ValidationIssue("wrong_adapter", "This action is not for the saved-file editor adapter."))
        if plan.risk != ActionRisk.MEDIUM or not plan.requires_confirmation:
            issues.append(ValidationIssue("unsafe_policy", "Code editor file changes always require confirmation."))
        if plan.target.locator.get("path") != snapshot.file_path:
            issues.append(ValidationIssue("target_changed", "The active saved file changed."))
        if plan.target.version != snapshot.fingerprint:
            issues.append(ValidationIssue("target_stale", "The saved file changed after the preview."))
        if len(plan.operations) != 1 or plan.operations[0].type not in {REPLACE_SELECTION, REPLACE_FILE}:
            issues.append(ValidationIssue("unsupported_plan", "This code editor adapter replaces one exact target."))
            return tuple(issues)
        operation = plan.operations[0]
        if operation.type == REPLACE_SELECTION:
            if snapshot.is_whole_file:
                issues.append(ValidationIssue("target_kind", "A selected-code action requires a non-empty range."))
            if int(operation.args.get("start", -1)) != snapshot.selection_start:
                issues.append(ValidationIssue("selection_changed", "The selected code start no longer matches."))
            if int(operation.args.get("end") or -1) != snapshot.selection_end:
                issues.append(ValidationIssue("selection_changed", "The selected code end no longer matches."))
            if operation.args.get("expected_selection_sha256") != snapshot.selection_fingerprint:
                issues.append(ValidationIssue("selection_changed", "The selected code changed after the preview."))
        else:
            if not snapshot.is_whole_file or snapshot.text:
                issues.append(ValidationIssue("target_kind", "The saved file is no longer empty."))
            if operation.args.get("expected_file_sha256") != snapshot.fingerprint:
                issues.append(ValidationIssue("file_changed", "The saved file changed after the preview."))
        replacement = operation.args.get("replacement_text")
        if not isinstance(replacement, str) or not replacement.strip():
            issues.append(ValidationIssue("empty_replacement", "The proposed code replacement is empty."))
        elif len(replacement) > 24_000:
            issues.append(ValidationIssue("replacement_too_large", "The proposed code replacement is too large."))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: VSCodeSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_vscode_preview(plan, snapshot)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        execution_started = time.perf_counter()
        self.last_execution_timing = {}
        if not confirmed:
            raise ActionValidationError(
                (ValidationIssue("confirmation_required", "Review and Apply the code diff first."),)
            )
        if not idempotency_key.strip():
            raise ActionValidationError(
                (ValidationIssue("idempotency_required", "The code editor action is missing its execution key."),)
            )
        cached = self._idempotent_results.get(idempotency_key)
        if cached is not None:
            return cached

        snapshot = self._snapshot_from_target(plan.target)
        snapshot_finished = time.perf_counter()
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        validation_finished = time.perf_counter()
        operation = plan.operations[0]
        replacement = str(operation.args["replacement_text"])
        next_text = (
            snapshot.text[:snapshot.selection_start]
            + replacement
            + snapshot.text[snapshot.selection_end:]
        )
        path = Path(snapshot.file_path)
        window_id = int(plan.target.locator.get("window_id") or 0)
        if window_id:
            try:
                from core.platform_utils import get_window_title

                if _title_looks_modified(str(get_window_title(window_id) or "")):
                    raise ActionValidationError(
                        (ValidationIssue("unsaved_editor", "Save the active editor file before applying this change."),)
                    )
            except ActionValidationError:
                raise
            except Exception:
                pass
        before_text = snapshot.selected_text
        self._atomic_write_utf8(path, next_text, has_bom=snapshot.has_utf8_bom)
        write_finished = time.perf_counter()
        written_raw = path.read_bytes()
        written_text = written_raw.decode("utf-8-sig")
        if written_text != next_text:
            raise RuntimeError("Code editor file verification failed after writing the replacement.")
        verification_finished = time.perf_counter()
        self.last_execution_timing = {
            "resnapshot_ms": round((snapshot_finished - execution_started) * 1000, 3),
            "validation_ms": round((validation_finished - snapshot_finished) * 1000, 3),
            "write_ms": round((write_finished - validation_finished) * 1000, 3),
            "readback_verify_ms": round((verification_finished - write_finished) * 1000, 3),
            "total_ms": round((verification_finished - execution_started) * 1000, 3),
        }

        updated_message = (
            f"Updated {path.name}; VS Code will reload the saved file change."
            if snapshot.editor_name.startswith("VS Code")
            else f"Updated {path.name}; {snapshot.editor_name} can reload the verified saved-file change."
        )
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message=updated_message,
            created=({"kind": "file_edit", "name": path.name},),
            journal=(
                {
                    "kind": "file_edit",
                    "path": str(path),
                    "start": snapshot.selection_start,
                    "before_text": before_text,
                    "after_text": replacement,
                    "before_fingerprint": snapshot.fingerprint,
                    "after_fingerprint": hashlib.sha256(written_raw).hexdigest(),
                },
            ),
            verification=(
                "The saved file fingerprint was rechecked immediately before Apply.",
                "The exact proposed replacement was read back from disk.",
                "No editor focus or keyboard input was used.",
            ),
        )
        self._idempotent_results[idempotency_key] = result
        return result

    @staticmethod
    def _snapshot_from_target(target: ActionTarget) -> VSCodeSnapshot:
        locator = target.locator
        path = Path(str(locator.get("path") or ""))
        if not path.is_file() or path.is_symlink():
            raise ValueError("The previewed VS Code file is no longer a regular file.")
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("The previewed VS Code file is no longer UTF-8.") from exc
        start = int(locator.get("start") or 0)
        end = int(locator.get("end") or 0)
        whole_file = str(locator.get("kind") or "") == "saved_empty_file"
        if start < 0 or end < start or end > len(text) or (not whole_file and end <= start):
            raise ValueError("The previewed code range is no longer valid.")
        if whole_file and (text or start != 0 or end != 0):
            raise ValueError("The previewed empty file is no longer empty.")
        selected = text[start:end]
        return VSCodeSnapshot(
            file_path=str(path),
            display_name=target.display_name,
            window_id=int(locator.get("window_id") or 0),
            pid=int(locator.get("pid") or 0),
            text=text,
            selected_text=selected,
            selection_start=start,
            selection_end=end,
            fingerprint=hashlib.sha256(raw).hexdigest(),
            selection_fingerprint=hashlib.sha256(selected.encode("utf-8")).hexdigest(),
            has_utf8_bom=raw.startswith(b"\xef\xbb\xbf"),
            is_whole_file=whole_file,
            editor_name=str(locator.get("editor_name") or "Code editor"),
        )

    @staticmethod
    def _atomic_write_utf8(path: Path, text: str, *, has_bom: bool) -> None:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
        payload = text.encode("utf-8")
        if has_bom:
            payload = b"\xef\xbb\xbf" + payload
        temporary_path = ""
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.wisp-", delete=False) as handle:
                temporary_path = handle.name
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, existing_mode)
            os.replace(temporary_path, path)
            temporary_path = ""
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass


def action_plan_from_dict(value: dict[str, Any]) -> ActionPlan:
    """Deserialize the exact plan approved by the preview UI."""
    target_value = value.get("target") if isinstance(value.get("target"), dict) else {}
    locator_value = target_value.get("locator") if isinstance(target_value.get("locator"), dict) else {}
    operations: list[ActionOperation] = []
    raw_operations = value.get("operations")
    for item in raw_operations if isinstance(raw_operations, list | tuple) else ():
        if not isinstance(item, dict):
            continue
        operations.append(
            ActionOperation(
                id=str(item.get("id") or ""),
                type=str(item.get("type") or ""),
                args=dict(item.get("args") or {}),
                depends_on=tuple(str(dep) for dep in (item.get("depends_on") or ())),
            )
        )
    risk_value = str(value.get("risk") or ActionRisk.MEDIUM.value)
    return ActionPlan(
        plan_id=str(value.get("plan_id") or ""),
        app=str(value.get("app") or ""),
        target=ActionTarget(
            app=str(target_value.get("app") or ""),
            display_name=str(target_value.get("display_name") or ""),
            locator={str(key): str(item) for key, item in locator_value.items()},
            version=str(target_value.get("version") or ""),
        ),
        summary=str(value.get("summary") or ""),
        operations=tuple(operations),
        risk=ActionRisk(risk_value),
        requires_confirmation=bool(value.get("requires_confirmation", True)),
    )
