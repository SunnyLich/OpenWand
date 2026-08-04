"""Preview/apply session state, cancellation, idempotency, and journal."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Protocol

from core.actions.interaction.contracts import (
    InteractionPlan,
    InteractionPreview,
    OperationReceipt,
    OperationType,
    PreviewStep,
)
from core.actions.interaction.driver import InteractionDriver, InteractionError, TransportKind
from core.actions.progress import ActionProgress, ActionProgressStage


class CancellationToken:
    """Thread-safe cancellation signal checked before every queued operation."""

    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()


class TargetIndicator(Protocol):
    """Passive visual feedback; implementations must never control OS input."""

    def show_mouse(self, bounds, label: str = "Wisp", *, pulse: bool = False) -> None: ...

    def show_text_caret(self, bounds, label: str = "Wisp agent") -> None: ...

    def clear(self) -> None: ...


@dataclass(frozen=True, slots=True)
class SessionResult:
    """Terminal interaction result with an honest per-operation journal."""

    plan_id: str
    status: str
    message: str
    journal: tuple[OperationReceipt, ...] = ()


class InteractionSession:
    """Own one exact preview-first interaction plan from targeting through verification."""

    def __init__(
        self,
        driver: InteractionDriver,
        progress: ActionProgress,
        *,
        cancellation: CancellationToken | None = None,
        indicator: TargetIndicator | None = None,
    ) -> None:
        self.driver = driver
        self.progress = progress
        self.cancellation = cancellation or CancellationToken()
        self.indicator = indicator
        self._prepared_plan: InteractionPlan | None = None
        self._results: dict[str, tuple[InteractionPlan, SessionResult]] = {}
        self._idempotency_claims: dict[str, InteractionPlan] = {}

    def prepare(self, plan: InteractionPlan) -> InteractionPreview:
        """Resolve and validate the exact plan, then expose it for approval without mutation."""
        self.progress.advance(ActionProgressStage.TARGETING, "Identifying the recorded application window...")
        self.progress.advance(ActionProgressStage.READING, "Reading the bounded semantic targets...")
        self.progress.advance(ActionProgressStage.PLANNING, "Resolving the registered semantic operations...")
        self.progress.advance(ActionProgressStage.VALIDATING, "Checking targets and preconditions...")
        try:
            self.driver.validate_plan(plan)
            self.progress.advance(ActionProgressStage.PREPARING_PREVIEW, "Building the exact interaction preview...")
            preview = InteractionPreview(
                plan_id=plan.plan_id,
                application=plan.application.app_id,
                window=plan.window.title or plan.window.window_id,
                summary=plan.summary,
                steps=tuple(self._preview_step(operation) for operation in plan.operations),
            )
            self._prepared_plan = plan
            self.progress.advance(ActionProgressStage.AWAITING_APPROVAL, plan.summary)
            return preview
        except Exception:
            self._clear_indicator()
            self.progress.advance(ActionProgressStage.FAILED, "The interaction plan was refused safely.")
            raise

    def execute(
        self,
        plan: InteractionPlan,
        *,
        confirmed: bool,
        idempotency_key: str,
    ) -> SessionResult:
        """Apply the previously previewed plan, re-resolving before every operation."""
        if not idempotency_key.strip():
            raise InteractionError("An idempotency key is required.")
        claimed_plan = self._idempotency_claims.get(idempotency_key)
        if claimed_plan is not None and claimed_plan != plan:
            raise InteractionError("The idempotency key was already used for a different interaction plan.")
        cached = self._results.get(idempotency_key)
        if cached is not None:
            _cached_plan, result = cached
            return result
        if claimed_plan is not None:
            raise InteractionError(
                "A previous attempt with this idempotency key did not finish safely; Wisp refused to repeat it."
            )
        if self._prepared_plan != plan:
            raise InteractionError("Apply must use the exact interaction plan shown in the preview.")
        if plan.requires_confirmation and not confirmed:
            raise InteractionError("Review and Apply the interaction preview first.")
        self._idempotency_claims[idempotency_key] = plan
        if self.cancellation.cancelled:
            result = SessionResult(plan.plan_id, "cancelled", "Cancelled before any interaction changes.")
            self.progress.advance(ActionProgressStage.CANCELLED, result.message)
            self._clear_indicator()
            self._results[idempotency_key] = (plan, result)
            return result

        journal: list[OperationReceipt] = []
        try:
            total = len(plan.operations)
            for index, operation in enumerate(plan.operations, start=1):
                if self.cancellation.cancelled:
                    result = SessionResult(
                        plan.plan_id,
                        "cancelled",
                        f"Cancelled after {len(journal)} of {total} operations.",
                        tuple(journal),
                    )
                    self.progress.advance(ActionProgressStage.CANCELLED, result.message)
                    self._clear_indicator()
                    self._results[idempotency_key] = (plan, result)
                    return result
                self.progress.advance(
                    ActionProgressStage.APPLYING,
                    f"Applying step {index} of {total}: {operation.type.value}...",
                )
                self._show_indicator(operation, pulse=False)
                journal.append(self.driver.execute(operation))
                self._show_indicator(operation, pulse=True)

            self.progress.advance(ActionProgressStage.VERIFYING, "Verifying the exact semantic results...")
            result = SessionResult(
                plan.plan_id,
                "complete",
                f"Applied and verified {len(journal)} semantic operations.",
                tuple(journal),
            )
            self.progress.advance(ActionProgressStage.COMPLETE, result.message)
            self._clear_indicator()
            self._results[idempotency_key] = (plan, result)
            return result
        except Exception:
            self._clear_indicator()
            self.progress.advance(ActionProgressStage.FAILED, "The interaction stopped safely before continuing.")
            raise

    def cancel(self) -> None:
        """Stop before the next queued operation; it never starts new work."""
        self.cancellation.cancel()

    def _show_indicator(self, operation, *, pulse: bool) -> None:
        bounds = operation.target.bounds
        if self.indicator is None or bounds is None:
            return
        try:
            if operation.type is OperationType.SET_VALUE:
                show_caret = getattr(self.indicator, "show_text_caret", None)
                if show_caret is not None:
                    show_caret(bounds, "Wisp agent")
                else:
                    self._clear_indicator()
                return
            if self.driver.transport_for(operation.type) is TransportKind.PHYSICAL_INPUT:
                show_mouse = getattr(self.indicator, "show_mouse", None)
                if show_mouse is not None:
                    show_mouse(bounds, "Wisp", pulse=pulse)
                else:
                    legacy = getattr(self.indicator, "show_target", None)
                    if legacy is not None:
                        legacy(bounds, "Wisp", pulse=pulse)
                return
            # Accessibility/API actions do not pretend that a mouse is present.
            self._clear_indicator()
        except Exception:
            # Visual feedback can fail closed without changing execution semantics.
            self._clear_indicator()

    def _clear_indicator(self) -> None:
        if self.indicator is None:
            return
        try:
            self.indicator.clear()
        except Exception:
            return

    def _preview_step(self, operation) -> PreviewStep:
        changes: list[str] = []
        if operation.type is OperationType.SET_VALUE:
            changes.append(f"Set value to {operation.args['value']!r}")
        elif operation.type is OperationType.TOGGLE:
            changes.append(f"Set toggle to {operation.args['state']}")
        elif operation.type is OperationType.SCROLL:
            changes.append(f"Scroll by {operation.args['amount']} bounded units")
        elif operation.type is OperationType.SELECT:
            changes.append("Select this exact item")
        elif operation.type is OperationType.INVOKE:
            changes.append("Invoke this exact control")
        else:
            changes.append("Read a bounded accessibility tree")
        return PreviewStep(
            operation_id=operation.id,
            operation_type=operation.type.value,
            target=operation.target.accessible_name or operation.target.automation_id,
            changes=tuple(changes),
            requires_focus=operation.requires_focus,
            requires_physical_input=(
                self.driver.transport_for(operation.type) is TransportKind.PHYSICAL_INPUT
            ),
            rollback=operation.rollback_limitations,
        )


__all__ = ["CancellationToken", "InteractionSession", "SessionResult"]
