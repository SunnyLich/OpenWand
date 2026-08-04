"""Shared preview-first orchestration for application action providers.

The runner deliberately knows nothing about Gmail, Office, browsers, or editor
APIs.  Runtime providers own those details and expose the small protocol below.
This keeps safety sequencing identical as Wisp adds more applications.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionPlan,
    ActionPreview,
    ValidationIssue,
)
from core.actions.errors import ActionUnavailableError, ActionValidationError
from core.actions.progress import ActionProgress, ActionProgressStage, ActionProgressUpdate
from core.actions.registry import ActionRegistry


@dataclass(frozen=True, slots=True)
class PlannedToolCall:
    """Validated output from Wisp's forced model-planning boundary."""

    tool_name: str
    arguments: dict[str, Any]
    visible_text: str = ""


@dataclass(frozen=True, slots=True)
class ActionRunOutcome:
    """Terminal result of one shared action run."""

    provider_id: str
    capability_type: str
    status: str
    preview: ActionPreview
    result: ActionExecutionResult | None = None


Planner = Callable[..., PlannedToolCall]
Approver = Callable[[ActionPreview], bool]


@runtime_checkable
class ActionRuntimeProvider(Protocol):
    """App-specific hooks consumed by :class:`ActionRunner`."""

    id: str
    app: str
    display_name: str

    def detects(self, context: dict[str, Any]) -> bool: ...

    def snapshot(self, context: dict[str, Any]) -> Any: ...

    def capabilities(self, snapshot: Any) -> tuple[ActionCapability, ...]: ...

    def planner_context(self, snapshot: Any) -> dict[str, Any]: ...

    def build_plan(
        self,
        capability: ActionCapability,
        arguments: dict[str, Any],
        snapshot: Any,
        visible_text: str,
    ) -> ActionPlan: ...

    def validate(self, plan: ActionPlan, snapshot: Any) -> tuple[ValidationIssue, ...]: ...

    def render_preview(self, plan: ActionPlan, snapshot: Any) -> ActionPreview: ...

    def execute(
        self,
        plan: ActionPlan,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> ActionExecutionResult: ...

    def verify(
        self,
        plan: ActionPlan,
        result: ActionExecutionResult,
    ) -> tuple[ValidationIssue, ...]: ...

    def rollback(
        self,
        plan: ActionPlan,
        result: ActionExecutionResult,
    ) -> ActionExecutionResult | None: ...


class ActionRuntimeProviderRegistry:
    """Ordered registry of providers implementing the complete runtime contract."""

    def __init__(self, providers: Iterable[ActionRuntimeProvider] = ()) -> None:
        self._providers: list[ActionRuntimeProvider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: ActionRuntimeProvider) -> None:
        if not provider.id.strip():
            raise ValueError("runtime provider id cannot be empty")
        if any(current.id == provider.id for current in self._providers):
            raise ValueError(f"runtime action provider is already registered: {provider.id}")
        self._providers.append(provider)

    def detect(self, context: dict[str, Any]) -> ActionRuntimeProvider | None:
        for provider in self._providers:
            try:
                if provider.detects(context):
                    return provider
            except Exception:
                continue
        return None

    def providers(self) -> tuple[ActionRuntimeProvider, ...]:
        return tuple(self._providers)


class ActionRunner:
    """Execute the invariant action pipeline once for every supported app."""

    def __init__(
        self,
        providers: ActionRuntimeProviderRegistry,
        *,
        planner: Planner,
        approver: Approver,
        progress_sink: Callable[[ActionProgressUpdate], None] | None = None,
        telemetry_sink: Callable[[ActionProgressUpdate], None] | None = None,
        planning_warning_seconds: float = 4.0,
    ) -> None:
        self._providers = providers
        self._planner = planner
        self._approver = approver
        self._progress_sink = progress_sink or (lambda _update: None)
        self._telemetry_sink = telemetry_sink
        self._planning_warning_seconds = max(0.0, float(planning_warning_seconds))

    def run(
        self,
        *,
        context: dict[str, Any],
        user_prompt: str,
        capability_type: str,
        planning_tool_name: str,
        provider_id: str = "",
        idempotency_key: str = "",
    ) -> ActionRunOutcome:
        provider = self._providers.detect(context)
        if provider is None:
            raise ActionUnavailableError("No action provider matches the active application.")
        if provider_id and provider.id != provider_id:
            raise ActionUnavailableError("The active application no longer matches the selected action provider.")

        progress = ActionProgress(
            capability_type,
            app=provider.app,
            sink=self._progress_sink,
            telemetry=self._telemetry_sink,
        )
        try:
            progress.advance(ActionProgressStage.TARGETING, "Checking the active application target...")
            progress.advance(ActionProgressStage.READING, "Reading a bounded snapshot from the application API...")
            snapshot = provider.snapshot(context)
            capabilities = provider.capabilities(snapshot)
            capability = next((item for item in capabilities if item.type == capability_type), None)
            if capability is None:
                raise ActionValidationError(
                    (ValidationIssue("unsupported_action", "This action is unavailable for the current target."),)
                )

            progress.advance(ActionProgressStage.PLANNING, "Drafting the exact typed application change...")
            planning_finished = threading.Event()

            def warn_if_slow() -> None:
                if not planning_finished.is_set():
                    progress.advance(
                        ActionProgressStage.PLANNING,
                        "The model is still drafting this application change; this may take a few more seconds.",
                    )

            warning = threading.Timer(self._planning_warning_seconds, warn_if_slow)
            warning.daemon = True
            warning.start()
            try:
                draft = self._planner(
                    tool_name=planning_tool_name,
                    tool_description=capability.description,
                    input_schema=capability.input_schema,
                    user_prompt=str(user_prompt),
                    app_context=provider.planner_context(snapshot),
                )
            finally:
                planning_finished.set()
                warning.cancel()
            if not isinstance(draft, PlannedToolCall) or draft.tool_name != planning_tool_name:
                raise ActionValidationError(
                    (ValidationIssue("planning_tool_mismatch", "The model did not use the required planning tool."),)
                )

            plan = provider.build_plan(capability, dict(draft.arguments), snapshot, draft.visible_text)
            progress.advance(ActionProgressStage.VALIDATING, "Validating the plan and target boundary...")
            issues = (
                *ActionRegistry(capabilities).validate_plan(plan),
                *provider.validate(plan, snapshot),
            )
            if issues:
                raise ActionValidationError(tuple(issues))

            progress.advance(ActionProgressStage.PREPARING_PREVIEW, "Building the exact approval preview...")
            preview = provider.render_preview(plan, snapshot)
            if preview.plan_id != plan.plan_id:
                raise ActionValidationError(
                    (ValidationIssue("preview_plan_mismatch", "The preview does not match the validated plan."),)
                )
            progress.advance(ActionProgressStage.AWAITING_APPROVAL, plan.summary)
            if not self._approver(preview):
                progress.advance(ActionProgressStage.CANCELLED, "Application change cancelled; nothing was changed.")
                return ActionRunOutcome(provider.id, capability.type, "cancelled", preview)

            progress.advance(ActionProgressStage.APPLYING, "Rechecking the target and applying the approved change...")
            fresh_snapshot = provider.snapshot(context)
            fresh_issues = provider.validate(plan, fresh_snapshot)
            if fresh_issues:
                raise ActionValidationError(tuple(fresh_issues))
            result = provider.execute(
                plan,
                confirmed=True,
                idempotency_key=idempotency_key.strip() or plan.plan_id,
            )

            progress.advance(ActionProgressStage.VERIFYING, "Verifying the application result...")
            try:
                verification_issues = provider.verify(plan, result)
            except Exception:
                provider.rollback(plan, result)
                raise
            if verification_issues:
                provider.rollback(plan, result)
                raise ActionValidationError(tuple(verification_issues))
            progress.advance(ActionProgressStage.COMPLETE, "Approved application change applied and verified.")
            return ActionRunOutcome(provider.id, capability.type, "applied", preview, result)
        except Exception:
            if progress.stage not in {
                ActionProgressStage.COMPLETE,
                ActionProgressStage.CANCELLED,
                ActionProgressStage.FAILED,
            }:
                progress.advance(ActionProgressStage.FAILED, "The application action failed; no unverified result was accepted.")
            raise


__all__ = [
    "ActionRunOutcome",
    "ActionRunner",
    "ActionRuntimeProvider",
    "ActionRuntimeProviderRegistry",
    "PlannedToolCall",
]
