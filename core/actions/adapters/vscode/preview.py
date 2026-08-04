"""Safe HTML/CSS diff preview for an exact VS Code action plan."""

from __future__ import annotations

import difflib
import uuid
from html import escape
from pathlib import Path

from core.actions.adapters.vscode.snapshot import VSCodeSnapshot
from core.actions.contracts import ActionPlan, ActionPreview
from core.actions.preview_templates import canvas_preview, chips

_MAX_PREVIEW_CHARS = 24_000


def render_vscode_untitled_preview(
    replacement: str,
    *,
    selected_text: str,
    display_name: str,
    summary: str,
) -> ActionPreview:
    """Preview an exact write to the editor range captured at hotkey time."""
    diff, changed_lines = _diff(selected_text, replacement, display_name)
    target_kind = "Selected text" if selected_text else "Insertion point"
    fragment = canvas_preview(
        app="Visual Studio Code",
        target=f"{display_name} · {target_kind}",
        title=summary,
        hero_html=(
            '<pre><code data-language="diff">'
            + escape(diff or "No textual difference was produced.", quote=False)
            + "</code></pre>"
        ),
        chips_html=chips((target_kind, f"{changed_lines} changed lines")),
        badge="VS",
    )
    return ActionPreview(
        plan_id=uuid.uuid4().hex,
        title="Apply code to Untitled tab",
        summary=summary,
        html=fragment,
        details=(),
        warnings=(),
    )


def render_vscode_preview(plan: ActionPlan, snapshot: VSCodeSnapshot) -> ActionPreview:
    """Render the model's exact replacement before touching the file."""
    operation = plan.operations[0]
    replacement = str(operation.args.get("replacement_text") or "")
    diff, changed_lines = _diff(snapshot.selected_text, replacement, Path(snapshot.file_path).name)

    fragment = canvas_preview(
        app="Visual Studio Code",
        target=f"{Path(snapshot.file_path).name} · {snapshot.selection_start}:{snapshot.selection_end}",
        title=plan.summary,
        hero_html=(
            '<pre><code data-language="diff">'
            + escape(diff or "No textual difference was produced.", quote=False)
            + "</code></pre>"
        ),
        chips_html=chips((f"{changed_lines} changed lines", "Selected range only")),
        badge="VS",
    )
    return ActionPreview(
        plan_id=plan.plan_id,
        title="Apply code fix",
        summary=plan.summary,
        html=fragment,
        details=(
            {
                "operation_id": operation.id,
                "type": operation.type,
                "label": f"Replace selected code in {Path(snapshot.file_path).name}",
            },
        ),
        warnings=(),
    )


def _diff(current: str, replacement: str, display_name: str) -> tuple[str, int]:
    """Return one bounded unified diff and its changed-line count."""
    diff_lines = list(
        difflib.unified_diff(
            current.splitlines(),
            replacement.splitlines(),
            fromfile=f"{display_name} (current)",
            tofile=f"{display_name} (proposed)",
            lineterm="",
        )
    )
    diff = "\n".join(diff_lines)
    if diff:
        diff += "\n"
    if len(diff) > _MAX_PREVIEW_CHARS:
        diff = f"{diff[:_MAX_PREVIEW_CHARS]}\n... diff preview truncated ...\n"
    changed_lines = sum(1 for line in diff.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    return diff, changed_lines
