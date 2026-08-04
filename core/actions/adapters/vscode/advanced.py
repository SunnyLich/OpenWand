"""Typed plans and previews for official VS Code Extension API actions."""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from html import escape
from pathlib import PurePosixPath
from typing import Any

from core.actions.adapters.vscode.preview import _diff
from core.actions.adapters.vscode.snapshot import VSCodeSnapshot
from core.actions.contracts import (
    ActionCapability,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ActionRisk,
    ValidationIssue,
)
from core.actions.preview_templates import canvas_preview, chips

FORMAT_DOCUMENT = "vscode.format_document@1"
UPSERT_TEST_FILE = "vscode.upsert_test_file@1"
RUN_REGISTERED_TASK = "vscode.run_registered_task@1"
RENAME_SYMBOL = "vscode.rename_symbol@1"

_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]{0,127}$")


def vscode_extension_capabilities() -> tuple[ActionCapability, ...]:
    """Return only operations intended for Wisp's authenticated extension bridge."""

    def capability(
        action_type: str,
        title: str,
        description: str,
        properties: dict[str, Any],
        required: list[str],
        risk: ActionRisk = ActionRisk.MEDIUM,
    ) -> ActionCapability:
        return ActionCapability(
            type=action_type,
            app="vscode",
            title=title,
            description=description,
            input_schema={
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            risk=risk,
            reversible=True,
        )

    common = {
        "expected_document_sha256": {"type": "string"},
        "expected_document_version": {"type": "number"},
        "preview_token": {"type": "string"},
    }
    return (
        capability(
            FORMAT_DOCUMENT,
            "Format active document",
            "Apply exact formatter edits returned by VS Code's registered formatter provider.",
            {**common, "formatted_text": {"type": "string"}},
            [*common, "formatted_text"],
        ),
        capability(
            UPSERT_TEST_FILE,
            "Generate or update one test file",
            "Apply one reviewed test-file edit through WorkspaceEdit.",
            {
                "relative_path": {"type": "string"},
                "expected_file_sha256": {"type": "string"},
                "current_text": {"type": "string"},
                "proposed_text": {"type": "string"},
                "preview_token": {"type": "string"},
            },
            ["relative_path", "expected_file_sha256", "proposed_text", "preview_token"],
        ),
        capability(
            RUN_REGISTERED_TASK,
            "Run registered task",
            "Run one existing allow-listed VS Code task by stable identifier; no command text is accepted.",
            {"task_id": {"type": "string"}, "task_label": {"type": "string"}},
            ["task_id", "task_label"],
            risk=ActionRisk.LOW,
        ),
        capability(
            RENAME_SYMBOL,
            "Rename symbol",
            "Apply exact workspace edits returned by VS Code's rename provider.",
            {**common, "new_name": {"type": "string"}, "affected_files": {"type": "array"}},
            [*common, "new_name", "affected_files"],
        ),
    )


def build_format_document_plan(
    snapshot: VSCodeSnapshot, *, formatted_text: str, preview_token: str, document_version: int
) -> ActionPlan:
    if not formatted_text or formatted_text == snapshot.text:
        raise ValueError("The registered formatter did not propose a document change.")
    return _plan(
        snapshot,
        FORMAT_DOCUMENT,
        "Format the active document",
        {
            "expected_document_sha256": snapshot.fingerprint,
            "expected_document_version": int(document_version),
            "preview_token": _token(preview_token),
            "formatted_text": formatted_text,
        },
    )


def build_test_file_plan(
    snapshot: VSCodeSnapshot,
    *,
    relative_path: str,
    current_text: str,
    proposed_text: str,
    expected_file_sha256: str,
    preview_token: str,
) -> ActionPlan:
    path = _relative_path(relative_path)
    if not proposed_text.strip() or proposed_text == current_text or len(proposed_text) > 48_000:
        raise ValueError("The proposed test file must contain one bounded, real change.")
    return _plan(
        snapshot,
        UPSERT_TEST_FILE,
        f"Generate or update {path}",
        {
            "relative_path": path,
            "expected_file_sha256": str(expected_file_sha256),
            "current_text": current_text,
            "proposed_text": proposed_text,
            "preview_token": _token(preview_token),
        },
    )


def build_registered_task_plan(snapshot: VSCodeSnapshot, *, task_id: str, task_label: str) -> ActionPlan:
    if not _TASK_ID.fullmatch(task_id):
        raise ValueError("The task must use one stable registered-task identifier.")
    if not str(task_label).strip():
        raise ValueError("The registered task needs a display label.")
    return _plan(
        snapshot,
        RUN_REGISTERED_TASK,
        f"Run registered task: {task_label}",
        {"task_id": task_id, "task_label": " ".join(task_label.split())[:160]},
        risk=ActionRisk.LOW,
    )


def build_rename_symbol_plan(
    snapshot: VSCodeSnapshot, *, new_name: str, affected_files: Sequence[str], preview_token: str, document_version: int
) -> ActionPlan:
    if not _IDENTIFIER.fullmatch(new_name):
        raise ValueError("The new symbol name is not a safe identifier.")
    files = tuple(str(item) for item in affected_files)
    if not 1 <= len(files) <= 20:
        raise ValueError("Rename preview must identify between 1 and 20 affected files.")
    return _plan(
        snapshot,
        RENAME_SYMBOL,
        f"Rename symbol to {new_name}",
        {
            "expected_document_sha256": snapshot.fingerprint,
            "expected_document_version": int(document_version),
            "preview_token": _token(preview_token),
            "new_name": new_name,
            "affected_files": files,
        },
    )


def validate_vscode_extension_plan(plan: ActionPlan, snapshot: VSCodeSnapshot) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    if plan.app != "vscode" or plan.target.app != "vscode":
        issues.append(ValidationIssue("wrong_adapter", "This action is not for VS Code."))
    if plan.target.locator != snapshot.target.locator:
        issues.append(ValidationIssue("target_changed", "The captured VS Code document or selection changed."))
    if plan.target.version != snapshot.fingerprint:
        issues.append(ValidationIssue("target_stale", "The document changed after preview."))
    if len(plan.operations) != 1 or plan.operations[0].type not in {
        FORMAT_DOCUMENT,
        UPSERT_TEST_FILE,
        RUN_REGISTERED_TASK,
        RENAME_SYMBOL,
    }:
        issues.append(ValidationIssue("unsupported_plan", "Use one registered VS Code API operation at a time."))
        return tuple(issues)
    operation = plan.operations[0]
    args = operation.args
    if operation.type != RUN_REGISTERED_TASK and not str(args.get("preview_token") or "").strip():
        issues.append(
            ValidationIssue("missing_preview_token", "The VS Code API preview token is missing.", operation.id)
        )
    if operation.type in {FORMAT_DOCUMENT, RENAME_SYMBOL}:
        if args.get("expected_document_sha256") != snapshot.fingerprint:
            issues.append(
                ValidationIssue("document_changed", "The document fingerprint no longer matches.", operation.id)
            )
        if (
            not isinstance(args.get("expected_document_version"), int)
            or int(args.get("expected_document_version", -1)) < 0
        ):
            issues.append(
                ValidationIssue(
                    "invalid_document_version", "The captured VS Code document version is invalid.", operation.id
                )
            )
    if operation.type == UPSERT_TEST_FILE:
        try:
            _relative_path(str(args.get("relative_path") or ""))
        except ValueError as exc:
            issues.append(ValidationIssue("unsafe_test_path", str(exc), operation.id))
        if len(str(args.get("proposed_text") or "")) > 48_000:
            issues.append(ValidationIssue("test_too_large", "The proposed test file is too large.", operation.id))
    elif operation.type == RUN_REGISTERED_TASK and not _TASK_ID.fullmatch(str(args.get("task_id") or "")):
        issues.append(
            ValidationIssue("unregistered_task", "Only a stable registered-task identifier is accepted.", operation.id)
        )
    elif operation.type == RENAME_SYMBOL and not _IDENTIFIER.fullmatch(str(args.get("new_name") or "")):
        issues.append(ValidationIssue("unsafe_symbol_name", "The new symbol name is invalid.", operation.id))
    return tuple(issues)


def render_vscode_extension_preview(plan: ActionPlan, snapshot: VSCodeSnapshot) -> ActionPreview:
    issues = validate_vscode_extension_plan(plan, snapshot)
    if issues:
        raise ValueError("; ".join(issue.message for issue in issues))
    operation = plan.operations[0]
    args = operation.args
    if operation.type == FORMAT_DOCUMENT:
        diff, changed = _diff(snapshot.text, str(args["formatted_text"]), snapshot.display_name)
        body = f'<pre><code data-language="diff">{escape(diff, quote=False)}</code></pre>'
        properties = (f"{changed} changed lines", "Whole document")
    elif operation.type == UPSERT_TEST_FILE:
        diff, changed = _diff(
            str(args.get("current_text") or ""), str(args["proposed_text"]), str(args["relative_path"])
        )
        body = f'<pre><code data-language="diff">{escape(diff, quote=False)}</code></pre>'
        properties = (f"{changed} changed lines", str(args["relative_path"]))
    elif operation.type == RENAME_SYMBOL:
        files = "".join(f"<li>{escape(str(item))}</li>" for item in args["affected_files"])
        body = f"<p>New symbol name: <strong>{escape(str(args['new_name']))}</strong></p><ul>{files}</ul>"
        properties = (f"{len(args['affected_files'])} affected files", "Workspace rename")
    else:
        body = f"<p>Registered task: <strong>{escape(str(args['task_label']))}</strong><br><code>{escape(str(args['task_id']))}</code></p>"
        properties = ("Registered task", "No generated shell command")
    html = canvas_preview(
        app="Visual Studio Code",
        target=snapshot.display_name,
        title=plan.summary,
        hero_html=body,
        chips_html=chips(properties),
        badge="VS",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="VS Code API action",
        summary=plan.summary,
        html=html,
        details=({"operation_id": operation.id, "type": operation.type, "label": plan.summary},),
        warnings=(),
    )


def _plan(
    snapshot: VSCodeSnapshot,
    action_type: str,
    summary: str,
    args: dict[str, Any],
    *,
    risk: ActionRisk = ActionRisk.MEDIUM,
) -> ActionPlan:
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="vscode",
        target=snapshot.target,
        summary=summary,
        operations=(ActionOperation(id=action_type.split(".", 1)[1].split("@", 1)[0], type=action_type, args=args),),
        risk=risk,
        requires_confirmation=True,
    )


def _token(value: str) -> str:
    token = str(value or "").strip()
    if len(token) < 16 or len(token) > 256:
        raise ValueError("The extension preview token is invalid.")
    return token


def _relative_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    path = PurePosixPath(text)
    if not text or path.is_absolute() or ".." in path.parts or ":" in text or len(text) > 240:
        raise ValueError("The test file must stay inside the current workspace.")
    return str(path)
