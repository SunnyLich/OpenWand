"""Shared-runner provider for an active PowerPoint desktop presentation."""

from __future__ import annotations

import re
from typing import Any

from core.actions.adapters.presentation.adapter import PresentationActionAdapter
from core.actions.adapters.presentation.capabilities import (
    CREATE_SLIDE,
    RESTYLE_SLIDE,
    UPSERT_SPEAKER_NOTES,
)
from core.actions.adapters.presentation.detection import is_powerpoint_desktop_app
from core.actions.adapters.presentation.plans import (
    build_create_slide_plan,
    build_restyle_slide_plan,
    build_speaker_notes_plan,
)
from core.actions.adapters.presentation.powerpoint_com import PowerPointComClient
from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionPlan,
    ActionPreview,
    ValidationIssue,
)

_POWERPOINT_SUFFIX = re.compile(r"\s+(?:[-\u2013\u2014])\s+PowerPoint\s*$", re.IGNORECASE)


class PowerPointDesktopRuntimeProvider:
    """Adapt PowerPoint's COM object model to the invariant ActionRunner hooks."""

    id = "powerpoint_desktop"
    app = "presentation"
    display_name = "Microsoft PowerPoint"

    def __init__(self, client: PowerPointComClient | None = None) -> None:
        self._client = client or PowerPointComClient()
        self._adapter: PresentationActionAdapter | None = None
        self._presentation_id = ""

    def detects(self, context: dict[str, Any]) -> bool:
        return is_powerpoint_desktop_app(_active_app(context))

    def snapshot(self, context: dict[str, Any]) -> Any:
        presentation_id = _presentation_identity(_active_app(context))
        if not presentation_id:
            raise RuntimeError("OpenWand could not identify the active PowerPoint presentation.")
        if self._adapter is None or self._presentation_id != presentation_id:
            self._presentation_id = presentation_id
            self._adapter = PresentationActionAdapter(
                self._client,
                backend="powerpoint_desktop",
                presentation_id=presentation_id,
            )
        return self._adapter.snapshot()

    def capabilities(self, snapshot: Any) -> tuple[ActionCapability, ...]:
        return self._require_adapter().capabilities()

    @staticmethod
    def planner_context(snapshot: Any) -> dict[str, Any]:
        return snapshot.model_context()

    @staticmethod
    def build_plan(
        capability: ActionCapability,
        arguments: dict[str, Any],
        snapshot: Any,
        visible_text: str,
    ) -> ActionPlan:
        del visible_text
        if capability.type == CREATE_SLIDE:
            return build_create_slide_plan(
                snapshot,
                title=str(arguments.get("title") or ""),
                body=str(arguments.get("body") or ""),
                layout=str(arguments.get("layout") or ""),
                position=str(arguments.get("position") or ""),
            )
        if capability.type == RESTYLE_SLIDE:
            return build_restyle_slide_plan(snapshot, preset=str(arguments.get("preset") or ""))
        if capability.type == UPSERT_SPEAKER_NOTES:
            return build_speaker_notes_plan(snapshot, notes=str(arguments.get("notes") or ""))
        raise ValueError("This PowerPoint operation is not registered.")

    def validate(self, plan: ActionPlan, snapshot: Any) -> tuple[ValidationIssue, ...]:
        return self._require_adapter().validate(plan, snapshot)

    def render_preview(self, plan: ActionPlan, snapshot: Any) -> ActionPreview:
        return self._require_adapter().render_preview(plan, snapshot)

    def execute(
        self,
        plan: ActionPlan,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> ActionExecutionResult:
        return self._require_adapter().execute(
            plan,
            confirmed=confirmed,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def verify(
        plan: ActionPlan,
        result: ActionExecutionResult,
    ) -> tuple[ValidationIssue, ...]:
        del plan
        if result.status != "applied" or not result.verification:
            return (ValidationIssue("unverified_result", "PowerPoint did not return a verified result."),)
        return ()

    def rollback(
        self,
        plan: ActionPlan,
        result: ActionExecutionResult,
    ) -> ActionExecutionResult | None:
        del plan
        if result.journal:
            self._require_adapter().rollback(dict(result.journal[0]))
        return None

    def _require_adapter(self) -> PresentationActionAdapter:
        if self._adapter is None:
            raise RuntimeError("PowerPoint has not been snapshotted for this action.")
        return self._adapter


def _active_app(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("active_app")
    return value if isinstance(value, dict) else {}


def _presentation_identity(active_app: dict[str, Any]) -> str:
    title = str(active_app.get("name") or active_app.get("title") or "").strip()
    return _POWERPOINT_SUFFIX.sub("", title).strip()


__all__ = ["PowerPointDesktopRuntimeProvider"]
