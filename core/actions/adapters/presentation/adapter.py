"""Preview-first presentation actions through injected application APIs only."""

from __future__ import annotations

from typing import Any

from core.actions.adapters.presentation.capabilities import (
    CREATE_SLIDE,
    LAYOUT_PRESETS,
    RESTYLE_SLIDE,
    STYLE_PRESETS,
    UPSERT_SPEAKER_NOTES,
    presentation_capabilities,
    presentation_registry,
)
from core.actions.adapters.presentation.client import (
    PresentationApiClient,
    PresentationMutationError,
    PresentationMutationReceipt,
)
from core.actions.adapters.presentation.preview import render_presentation_preview
from core.actions.adapters.presentation.snapshot import PresentationSnapshot, capture_presentation_snapshot
from core.actions.contracts import (
    ActionCapability,
    ActionExecutionResult,
    ActionOperation,
    ActionPlan,
    ActionPreview,
    ActionRisk,
    ActionTarget,
    ValidationIssue,
)
from core.actions.errors import ActionValidationError


class PresentationActionAdapter:
    """Plan, validate, execute, verify, and roll back one API mutation."""

    def __init__(
        self,
        client: PresentationApiClient,
        *,
        backend: str,
        presentation_id: str,
        selected_slide_id: str = "",
    ) -> None:
        self.client = client
        self.backend = str(backend or "")
        self.presentation_id = str(presentation_id or "")
        self.selected_slide_id = str(selected_slide_id or "")
        self._registry = presentation_registry()
        self._idempotent_results: dict[str, tuple[str, ActionExecutionResult]] = {}

    def detect(self) -> bool:
        try:
            self.snapshot()
            return True
        except Exception:
            return False

    def capabilities(self) -> tuple[ActionCapability, ...]:
        return presentation_capabilities(self.backend)

    def snapshot(self) -> PresentationSnapshot:
        return capture_presentation_snapshot(
            self.client,
            backend=self.backend,
            presentation_id=self.presentation_id,
            selected_slide_id=self.selected_slide_id,
        )

    def validate(self, plan: ActionPlan, snapshot: PresentationSnapshot) -> tuple[ValidationIssue, ...]:
        """Apply deterministic structural, freshness, and action-specific checks."""
        issues = list(self._registry.validate_plan(plan))
        if plan.app != "presentation":
            issues.append(ValidationIssue("wrong_adapter", "This adapter can only run presentation plans."))
        if not plan.plan_id.strip():
            issues.append(ValidationIssue("missing_plan_id", "The presentation plan has no identity."))
        if not plan.requires_confirmation:
            issues.append(ValidationIssue("confirmation_policy", "Presentation changes must require approval."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(ValidationIssue("target_changed", "The presentation or selected slide has changed."))
        if plan.target.version != snapshot.fingerprint:
            issues.append(ValidationIssue("target_stale", "The presentation revision changed after preview."))
        if len(plan.operations) != 1:
            issues.append(ValidationIssue("single_operation_required", "Review one presentation change at a time."))
            return tuple(issues)

        operation = plan.operations[0]
        if operation.type not in {capability.type for capability in self.capabilities()}:
            issues.append(ValidationIssue(
                "backend_capability_unavailable",
                "The active presentation API does not support this reviewed operation.",
                operation.id,
            ))
            return tuple(issues)
        args = operation.args
        if operation.type == CREATE_SLIDE:
            title = args.get("title")
            body = args.get("body")
            layout = args.get("layout")
            position = args.get("position")
            if not isinstance(title, str) or len(title) > 200:
                issues.append(ValidationIssue("invalid_title", "Slide titles are limited to 200 characters.", operation.id))
            if not isinstance(body, str) or len(body) > 8_000:
                issues.append(ValidationIssue("invalid_body", "Slide bodies are limited to 8,000 characters.", operation.id))
            if layout not in LAYOUT_PRESETS:
                issues.append(ValidationIssue("invalid_layout", "The requested slide layout is not a Wisp preset.", operation.id))
            if position == "after_selected" and not snapshot.selected_slide_id:
                issues.append(ValidationIssue("selection_required", "Select a slide or create the new slide at the end.", operation.id))
        elif operation.type == RESTYLE_SLIDE:
            slide_id = str(args.get("slide_id") or "")
            if not snapshot.selected_slide_id or slide_id != snapshot.selected_slide_id:
                issues.append(ValidationIssue("selected_slide_mismatch", "Restyle can target only the captured selected slide.", operation.id))
            if snapshot.slide(slide_id) is None:
                issues.append(ValidationIssue("slide_missing", "The selected slide no longer exists.", operation.id))
            if args.get("preset") not in STYLE_PRESETS:
                issues.append(ValidationIssue("invalid_style", "The requested style is not a bounded Wisp preset.", operation.id))
            if args.get("preserve_content") is not True:
                issues.append(ValidationIssue("content_preservation_required", "Restyling must preserve all slide content.", operation.id))
        elif operation.type == UPSERT_SPEAKER_NOTES:
            slide_id = str(args.get("slide_id") or "")
            if not snapshot.selected_slide_id or slide_id != snapshot.selected_slide_id:
                issues.append(ValidationIssue("selected_slide_mismatch", "Notes can target only the captured selected slide.", operation.id))
            if snapshot.slide(slide_id) is None:
                issues.append(ValidationIssue("slide_missing", "The selected slide no longer exists.", operation.id))
            notes = args.get("notes")
            if not isinstance(notes, str) or len(notes) > 12_000:
                issues.append(ValidationIssue("invalid_notes", "Speaker notes are limited to 12,000 characters.", operation.id))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: PresentationSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_presentation_preview(plan, snapshot)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        """Revalidate, call one explicit API method, read back, and cache the result."""
        if plan.requires_confirmation and not confirmed:
            raise ActionValidationError((ValidationIssue(
                "confirmation_required", "Review and approve the presentation preview before applying."
            ),))
        key = str(idempotency_key or "").strip()
        if not key:
            raise ActionValidationError((ValidationIssue(
                "idempotency_required", "An idempotency key is required before applying."
            ),))
        cached = self._idempotent_results.get(key)
        if cached is not None:
            cached_plan_id, result = cached
            if cached_plan_id != plan.plan_id:
                raise ActionValidationError((ValidationIssue(
                    "idempotency_conflict", "This idempotency key belongs to another presentation plan."
                ),))
            return result

        before = self.snapshot()
        issues = self.validate(plan, before)
        if issues:
            raise ActionValidationError(issues)
        operation = plan.operations[0]
        try:
            receipt = PresentationMutationReceipt.from_value(
                self._apply(operation, before, idempotency_key=key)
            )
        except PresentationMutationError as exc:
            if exc.rollback_token:
                self.client.rollback(self.presentation_id, rollback_token=exc.rollback_token)
            raise RuntimeError(f"Presentation API mutation failed: {exc}") from exc

        try:
            after = self.snapshot()
            verification = self._verify_effect(operation, before, after, receipt)
        except Exception as exc:
            rolled_back = self.client.rollback(
                self.presentation_id, rollback_token=receipt.rollback_token
            )
            rollback_verified = False
            if rolled_back:
                try:
                    rollback_verified = self.snapshot().semantic_fingerprint == before.semantic_fingerprint
                except Exception:
                    rollback_verified = False
            state = "rolled back" if rollback_verified else "rollback could not be verified"
            raise RuntimeError(f"Presentation verification failed and the change was {state}: {exc}") from exc

        created = (
            ({"kind": "slide", "name": receipt.slide_id},)
            if operation.type == CREATE_SLIDE else ()
        )
        journal = ({
            "kind": "presentation_api_change",
            "operation": operation.type,
            "backend": before.backend,
            "presentation_id": before.presentation_id,
            "slide_id": receipt.slide_id or str(operation.args.get("slide_id") or ""),
            "before_revision": before.revision,
            "after_revision": after.revision,
            "before_semantic_fingerprint": before.semantic_fingerprint,
            "rollback": "presentation_api_rollback",
            "rollback_token": receipt.rollback_token,
        },)
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message="Applied and verified the reviewed presentation API change.",
            created=created,
            journal=journal,
            verification=verification,
        )
        self._idempotent_results[key] = (plan.plan_id, result)
        return result

    def rollback(self, journal_entry: dict[str, Any]) -> bool:
        """Use only the API rollback token recorded in a successful journal."""
        if str(journal_entry.get("presentation_id") or "") != self.presentation_id:
            return False
        token = str(journal_entry.get("rollback_token") or "").strip()
        expected = str(journal_entry.get("before_semantic_fingerprint") or "").strip()
        if not token or not expected:
            return False
        if not self.client.rollback(self.presentation_id, rollback_token=token):
            return False
        return self.snapshot().semantic_fingerprint == expected

    def _apply(
        self,
        operation: ActionOperation,
        before: PresentationSnapshot,
        *,
        idempotency_key: str,
    ) -> Any:
        args = operation.args
        common = {
            "expected_revision": before.revision,
            "idempotency_key": idempotency_key,
        }
        if operation.type == CREATE_SLIDE:
            return self.client.create_slide(
                self.presentation_id,
                title=str(args["title"]),
                body=str(args["body"]),
                layout=str(args["layout"]),
                position=str(args["position"]),
                after_slide_id=before.selected_slide_id,
                **common,
            )
        if operation.type == RESTYLE_SLIDE:
            return self.client.restyle_slide(
                self.presentation_id,
                slide_id=str(args["slide_id"]),
                preset=str(args["preset"]),
                preserve_content=True,
                **common,
            )
        return self.client.upsert_speaker_notes(
            self.presentation_id,
            slide_id=str(args["slide_id"]),
            notes=str(args["notes"]),
            **common,
        )

    @staticmethod
    def _verify_effect(
        operation: ActionOperation,
        before: PresentationSnapshot,
        after: PresentationSnapshot,
        receipt: PresentationMutationReceipt,
    ) -> tuple[str, ...]:
        if after.revision != receipt.revision:
            raise RuntimeError("The readback revision does not match the mutation receipt.")
        if operation.type == CREATE_SLIDE:
            created = after.slide(receipt.slide_id)
            if created is None:
                raise RuntimeError("The created slide was not present during readback.")
            if (created.title, created.body, created.style_preset) != (
                str(operation.args["title"]), str(operation.args["body"]), str(operation.args["layout"])
            ):
                raise RuntimeError("The created slide content or layout did not match the preview.")
            remaining = tuple(slide for slide in after.slides if slide.slide_id != created.slide_id)
            if tuple(_slide_content(slide) for slide in remaining) != tuple(
                _slide_content(slide) for slide in before.slides
            ):
                raise RuntimeError("Slides outside the reviewed creation changed unexpectedly.")
            expected_index = len(before.slides)
            if operation.args["position"] == "after_selected":
                selected = before.slide(before.selected_slide_id)
                expected_index = (selected.index + 1) if selected is not None else expected_index
            if created.index != expected_index:
                raise RuntimeError("The new slide was created at a different position than previewed.")
            return (f"Verified slide {created.slide_id} content, layout, and position.",)

        slide_id = str(operation.args["slide_id"])
        old = before.slide(slide_id)
        new = after.slide(slide_id)
        if old is None or new is None:
            raise RuntimeError("The selected slide disappeared during verification.")
        unchanged = tuple(slide for slide in after.slides if slide.slide_id != slide_id)
        expected_unchanged = tuple(slide for slide in before.slides if slide.slide_id != slide_id)
        if unchanged != expected_unchanged:
            raise RuntimeError("A slide outside the reviewed target changed unexpectedly.")
        if operation.type == RESTYLE_SLIDE:
            if (new.title, new.body, new.speaker_notes) != (old.title, old.body, old.speaker_notes):
                raise RuntimeError("Restyling changed slide content.")
            if new.style_preset != operation.args["preset"]:
                raise RuntimeError("The selected slide did not retain the reviewed style preset.")
            return (f"Verified preset {new.style_preset} while preserving slide content.",)
        if (new.title, new.body, new.style_preset) != (old.title, old.body, old.style_preset):
            raise RuntimeError("Updating notes changed visible slide content or style.")
        if new.speaker_notes != operation.args["notes"]:
            raise RuntimeError("The selected slide did not retain the reviewed speaker notes.")
        return ("Verified the exact speaker notes through API readback.",)


def action_plan_from_dict(value: dict[str, Any]) -> ActionPlan:
    """Deserialize a local trusted action-plan wire value."""
    target_value = value.get("target") if isinstance(value.get("target"), dict) else {}
    operations = tuple(
        ActionOperation(
            id=str(item.get("id") or ""),
            type=str(item.get("type") or ""),
            args=dict(item.get("args") or {}),
            depends_on=tuple(item.get("depends_on") or ()),
        )
        for item in (value.get("operations") or ())
        if isinstance(item, dict)
    )
    return ActionPlan(
        plan_id=str(value.get("plan_id") or ""),
        app=str(value.get("app") or ""),
        target=ActionTarget(
            app=str(target_value.get("app") or ""),
            display_name=str(target_value.get("display_name") or ""),
            locator={str(key): str(item) for key, item in dict(target_value.get("locator") or {}).items()},
            version=str(target_value.get("version") or ""),
        ),
        summary=str(value.get("summary") or ""),
        operations=operations,
        risk=ActionRisk(str(value.get("risk") or ActionRisk.MEDIUM.value)),
        requires_confirmation=bool(value.get("requires_confirmation", True)),
    )


def _slide_content(slide: Any) -> tuple[str, str, str, str, str]:
    """Compare slide content while allowing insertion to shift numeric indexes."""
    return (
        slide.slide_id,
        slide.title,
        slide.body,
        slide.speaker_notes,
        slide.style_preset,
    )
