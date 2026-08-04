"""Build and parse exact browser form-fill plans."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from core.actions.adapters.browser.capabilities import FILL_FORM
from core.actions.adapters.browser.snapshot import BrowserFormSnapshot
from core.actions.contracts import ActionOperation, ActionPlan, ActionRisk, ActionTarget


def parse_form_assignments(model_text: str) -> list[dict[str, str]]:
    text = str(model_text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    value = json.loads(text)
    rows = value.get("assignments") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        raise ValueError("The model did not return a form assignment list.")
    return [
        {"field_id": str(item.get("field_id") or ""), "value": str(item.get("value") or "")}
        for item in rows
        if isinstance(item, dict)
    ]


def build_fill_form_plan(
    snapshot: BrowserFormSnapshot,
    assignments: list[dict[str, Any]],
    *,
    summary: str = "Fill the current web form",
) -> ActionPlan:
    if not assignments:
        raise ValueError("No form values were proposed.")
    if len(assignments) > 20:
        raise ValueError("A single browser action can fill at most 20 fields.")
    fields = {field.field_id: field for field in snapshot.fields}
    operations: list[ActionOperation] = []
    seen: set[str] = set()
    for index, assignment in enumerate(assignments, 1):
        field_id = str(assignment.get("field_id") or "").strip()
        value = str(assignment.get("value") or "")
        if not field_id or field_id in seen or field_id not in fields:
            raise ValueError(f"The proposed browser field {field_id or '(missing)'} is invalid or duplicated.")
        if len(value) > 4_000:
            raise ValueError(f"The proposed value for {field_id} is too long.")
        field = fields[field_id]
        if field.kind == "select" and value not in field.options:
            raise ValueError(f"{field.label} must use one of the page's available options.")
        if value == field.value:
            continue
        seen.add(field_id)
        operations.append(
            ActionOperation(
                id=f"fill_{index}",
                type=FILL_FORM,
                args={
                    "field_id": field_id,
                    "selector": field.selector,
                    "label": field.label,
                    "kind": field.kind,
                    "expected_value": field.value,
                    "value": value,
                },
            )
        )
    if not operations:
        raise ValueError("The model did not propose any form changes.")
    clean_summary = " ".join(str(summary or "").split())[:180] or "Fill the current web form"
    return ActionPlan(
        plan_id=uuid.uuid4().hex,
        app="browser",
        target=snapshot.target,
        summary=clean_summary,
        operations=tuple(operations),
        risk=ActionRisk.MEDIUM,
        requires_confirmation=True,
    )


def action_plan_from_dict(value: dict[str, Any]) -> ActionPlan:
    target = value.get("target") if isinstance(value.get("target"), dict) else {}
    return ActionPlan(
        plan_id=str(value.get("plan_id") or ""),
        app=str(value.get("app") or ""),
        target=ActionTarget(
            app=str(target.get("app") or ""),
            display_name=str(target.get("display_name") or ""),
            locator={str(key): str(item) for key, item in dict(target.get("locator") or {}).items()},
            version=str(target.get("version") or ""),
        ),
        summary=str(value.get("summary") or ""),
        operations=tuple(
            ActionOperation(
                id=str(item.get("id") or ""),
                type=str(item.get("type") or ""),
                args=dict(item.get("args") or {}),
                depends_on=tuple(item.get("depends_on") or ()),
            )
            for item in (value.get("operations") or ())
            if isinstance(item, dict)
        ),
        risk=ActionRisk(str(value.get("risk") or ActionRisk.MEDIUM.value)),
        requires_confirmation=bool(value.get("requires_confirmation", True)),
    )
