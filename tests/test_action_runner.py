from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

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
from core.actions.runner import (
    ActionRunner,
    ActionRuntimeProviderRegistry,
    PlannedToolCall,
)


@dataclass(frozen=True)
class Snapshot:
    version: str
    value: str


class FakeProvider:
    id = "fake"
    app = "fake_app"
    display_name = "Fake App"

    def __init__(self) -> None:
        self.snapshots = [Snapshot("v1", "before"), Snapshot("v1", "before")]
        self.executions = 0
        self.rollbacks = 0
        self.verification_issues: tuple[ValidationIssue, ...] = ()

    def detects(self, context: dict[str, Any]) -> bool:
        return context.get("app") == self.app

    def snapshot(self, _context: dict[str, Any]) -> Snapshot:
        return self.snapshots.pop(0)

    def capabilities(self, _snapshot: Snapshot) -> tuple[ActionCapability, ...]:
        return (
            ActionCapability(
                type="fake.change@1",
                app=self.app,
                title="Change",
                description="Change one fake value.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
                risk=ActionRisk.MEDIUM,
                reversible=True,
            ),
        )

    def planner_context(self, snapshot: Snapshot) -> dict[str, Any]:
        return {"version": snapshot.version, "value": snapshot.value}

    def build_plan(
        self,
        capability: ActionCapability,
        arguments: dict[str, Any],
        snapshot: Snapshot,
        visible_text: str,
    ) -> ActionPlan:
        return ActionPlan(
            plan_id="plan-1",
            app=self.app,
            target=ActionTarget(self.app, self.display_name, {"id": "one"}, snapshot.version),
            summary=visible_text or "Change the value",
            operations=(ActionOperation("change", capability.type, arguments),),
            risk=capability.risk,
        )

    def validate(self, plan: ActionPlan, snapshot: Snapshot) -> tuple[ValidationIssue, ...]:
        if plan.target.version != snapshot.version:
            return (ValidationIssue("target_stale", "The fake target changed."),)
        return ()

    def render_preview(self, plan: ActionPlan, _snapshot: Snapshot) -> ActionPreview:
        return ActionPreview(plan.plan_id, "Preview", plan.summary, "<p>preview</p>")

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        assert confirmed and idempotency_key
        self.executions += 1
        return ActionExecutionResult(plan.plan_id, "applied", "changed", journal=({"before": "before"},))

    def verify(self, _plan: ActionPlan, _result: ActionExecutionResult) -> tuple[ValidationIssue, ...]:
        return self.verification_issues

    def rollback(self, _plan: ActionPlan, _result: ActionExecutionResult) -> ActionExecutionResult | None:
        self.rollbacks += 1
        return None


def _planner(**kwargs: Any) -> PlannedToolCall:
    assert kwargs["tool_name"] == "fake_plan_change"
    assert kwargs["app_context"]["version"] == "v1"
    return PlannedToolCall("fake_plan_change", {"value": "after"}, "Change before to after")


def test_runner_owns_complete_preview_first_sequence() -> None:
    provider = FakeProvider()
    stages: list[str] = []
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=_planner,
        approver=lambda preview: preview.title == "Preview",
        progress_sink=lambda update: stages.append(update.stage),
    )

    outcome = runner.run(
        context={"app": "fake_app"},
        user_prompt="change it",
        capability_type="fake.change@1",
        planning_tool_name="fake_plan_change",
        provider_id="fake",
    )

    assert outcome.status == "applied"
    assert provider.executions == 1
    assert stages == [
        "targeting",
        "reading",
        "planning",
        "validating",
        "preparing_preview",
        "awaiting_approval",
        "applying",
        "verifying",
        "complete",
    ]


def test_runner_cancel_never_executes() -> None:
    provider = FakeProvider()
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=_planner,
        approver=lambda _preview: False,
    )
    outcome = runner.run(
        context={"app": "fake_app"},
        user_prompt="change it",
        capability_type="fake.change@1",
        planning_tool_name="fake_plan_change",
    )
    assert outcome.status == "cancelled"
    assert provider.executions == 0
    assert len(provider.snapshots) == 1


def test_runner_revalidates_fresh_snapshot_before_execute() -> None:
    provider = FakeProvider()
    provider.snapshots[1] = Snapshot("v2", "someone changed it")
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=_planner,
        approver=lambda _preview: True,
    )
    with pytest.raises(ActionValidationError, match="changed"):
        runner.run(
            context={"app": "fake_app"},
            user_prompt="change it",
            capability_type="fake.change@1",
            planning_tool_name="fake_plan_change",
        )
    assert provider.executions == 0


def test_runner_rolls_back_failed_verification() -> None:
    provider = FakeProvider()
    provider.verification_issues = (ValidationIssue("verify_failed", "Read-back did not match."),)
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=_planner,
        approver=lambda _preview: True,
    )
    with pytest.raises(ActionValidationError, match="Read-back"):
        runner.run(
            context={"app": "fake_app"},
            user_prompt="change it",
            capability_type="fake.change@1",
            planning_tool_name="fake_plan_change",
        )
    assert provider.executions == 1
    assert provider.rollbacks == 1


def test_runner_rejects_wrong_forced_tool() -> None:
    provider = FakeProvider()
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=lambda **_kwargs: PlannedToolCall("some_other_tool", {"value": "after"}),
        approver=lambda _preview: True,
    )
    with pytest.raises(ActionValidationError, match="required planning tool"):
        runner.run(
            context={"app": "fake_app"},
            user_prompt="change it",
            capability_type="fake.change@1",
            planning_tool_name="fake_plan_change",
        )
