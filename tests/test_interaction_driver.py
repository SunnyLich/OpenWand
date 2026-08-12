"""Deterministic Slice 1 tests for OpenWand's semantic interaction fallback."""

from __future__ import annotations

import pytest

from core.actions.interaction import (
    ApplicationIdentity,
    Bounds,
    CancellationToken,
    FakeAccessibilityBackend,
    FakeElement,
    InteractionDriver,
    InteractionPlan,
    InteractionSession,
    OperationType,
    SemanticOperation,
    StateCondition,
    StateField,
    WindowIdentity,
)
from core.actions.interaction.driver import (
    AmbiguousElementError,
    InteractionError,
    PreconditionsChangedError,
    StaleElementError,
    UnsupportedOperationError,
    VerificationError,
)
from core.actions.progress import ActionProgress, ActionProgressUpdate

APP = ApplicationIdentity("openwand_test_form", process_id=42, executable="openwand-test-form.exe")
WINDOW = WindowIdentity("window-7", "OpenWand interaction test form")


def _element(
    element_id: str,
    name: str,
    role: str,
    *operations: OperationType,
    automation_id: str = "",
    ancestor_path: tuple[str, ...] = ("Settings",),
    value: str = "",
) -> FakeElement:
    return FakeElement(
        element_id=element_id,
        application=APP,
        window=WINDOW,
        role=role,
        accessible_name=name,
        automation_id=automation_id,
        ancestor_path=ancestor_path,
        bounds=Bounds(100, 120, 240, 32),
        supported_operations=frozenset(operations),
        value=value,
    )


def _plan(*operations: SemanticOperation) -> InteractionPlan:
    return InteractionPlan(
        plan_id="plan-1",
        application=APP,
        window=WINDOW,
        summary="Update the OpenWand-owned test form",
        operations=operations,
    )


def _session(
    backend: FakeAccessibilityBackend,
    *,
    token: CancellationToken | None = None,
    indicator=None,
):
    updates: list[ActionProgressUpdate] = []
    progress = ActionProgress("interaction.plan-1", app=APP.app_id, sink=updates.append)
    return InteractionSession(
        InteractionDriver((backend,)),
        progress,
        cancellation=token,
        indicator=indicator,
    ), updates


def test_exact_semantic_resolution_ignores_bounds_movement() -> None:
    field = _element(
        "field-1",
        "Display name",
        "edit",
        OperationType.SET_VALUE,
        automation_id="display-name",
        value="Before",
    )
    locator = field.locator()
    backend = FakeAccessibilityBackend((field,))

    field.bounds = Bounds(500, 300, 300, 32)

    assert backend.resolve(locator) is field


def test_ambiguous_semantic_match_is_refused() -> None:
    first = _element("save-1", "Save", "button", OperationType.INVOKE)
    second = _element("save-2", "Save", "button", OperationType.INVOKE)
    backend = FakeAccessibilityBackend((first, second))

    with pytest.raises(AmbiguousElementError, match="more than one"):
        backend.resolve(first.locator())


def test_changed_element_identity_is_stale() -> None:
    button = _element("save-1", "Save", "button", OperationType.INVOKE)
    locator = button.locator()
    backend = FakeAccessibilityBackend((button,))

    button.element_id = "replacement-save-button"

    with pytest.raises(StaleElementError, match="identity changed"):
        backend.resolve(locator)


def test_precondition_change_after_preview_is_refused_before_mutation() -> None:
    field = _element("field-1", "Display name", "edit", OperationType.SET_VALUE, value="Before")
    operation = SemanticOperation(
        "set-name",
        OperationType.SET_VALUE,
        field.locator(),
        {"value": "After"},
        preconditions=(StateCondition(StateField.VALUE, "Before"),),
    )
    session, _updates = _session(FakeAccessibilityBackend((field,)))
    plan = _plan(operation)
    session.prepare(plan)

    field.value = "User changed this"

    with pytest.raises(PreconditionsChangedError):
        session.execute(plan, confirmed=True, idempotency_key="apply-1")
    assert field.value == "User changed this"


def test_cancel_before_apply_performs_zero_mutations() -> None:
    field = _element("field-1", "Display name", "edit", OperationType.SET_VALUE, value="Before")
    operation = SemanticOperation(
        "set-name",
        OperationType.SET_VALUE,
        field.locator(),
        {"value": "After"},
    )
    session, updates = _session(FakeAccessibilityBackend((field,)))
    plan = _plan(operation)
    session.prepare(plan)
    session.cancel()

    result = session.execute(plan, confirmed=True, idempotency_key="cancel-1")

    assert result.status == "cancelled"
    assert result.journal == ()
    assert field.value == "Before"
    assert updates[-1].stage == "cancelled"


def test_sensitive_editable_field_is_refused_during_preview() -> None:
    field = _element("password-1", "Account secret", "edit", OperationType.SET_VALUE)
    field.sensitive = True
    operation = SemanticOperation(
        "set-secret",
        OperationType.SET_VALUE,
        field.locator(),
        {"value": "not-allowed"},
    )
    session, updates = _session(FakeAccessibilityBackend((field,)))

    with pytest.raises(UnsupportedOperationError, match="does not enter credentials"):
        session.prepare(_plan(operation))
    assert field.value == ""
    assert updates[-1].stage == "failed"


def test_cancellation_stops_queued_operations() -> None:
    token = CancellationToken()
    first = _element("field-1", "First name", "edit", OperationType.SET_VALUE, value="A")
    second = _element("field-2", "Last name", "edit", OperationType.SET_VALUE, value="B")
    backend = FakeAccessibilityBackend((first, second), after_execute=lambda _operation, _element: token.cancel())
    operations = (
        SemanticOperation("set-first", OperationType.SET_VALUE, first.locator(), {"value": "C"}),
        SemanticOperation("set-last", OperationType.SET_VALUE, second.locator(), {"value": "D"}),
    )
    session, _updates = _session(backend, token=token)
    plan = _plan(*operations)
    session.prepare(plan)

    result = session.execute(plan, confirmed=True, idempotency_key="cancel-queued")

    assert result.status == "cancelled"
    assert len(result.journal) == 1
    assert first.value == "C"
    assert second.value == "B"


def test_idempotency_replays_verified_result_without_reinvoking() -> None:
    button = _element("save-1", "Save", "button", OperationType.INVOKE)
    operation = SemanticOperation("save", OperationType.INVOKE, button.locator())
    session, _updates = _session(FakeAccessibilityBackend((button,)))
    plan = _plan(operation)
    session.prepare(plan)

    first = session.execute(plan, confirmed=True, idempotency_key="save-once")
    second = session.execute(plan, confirmed=True, idempotency_key="save-once")

    assert first == second
    assert button.invocation_count == 1


def test_verification_failure_stops_the_session() -> None:
    field = _element("field-1", "Display name", "edit", OperationType.SET_VALUE, value="Before")

    def corrupt_result(_operation: SemanticOperation, element: FakeElement) -> None:
        element.value = "Unexpected"

    operation = SemanticOperation(
        "set-name",
        OperationType.SET_VALUE,
        field.locator(),
        {"value": "After"},
    )
    session, updates = _session(FakeAccessibilityBackend((field,), after_execute=corrupt_result))
    plan = _plan(operation)
    session.prepare(plan)

    with pytest.raises(VerificationError, match="postcondition failed"):
        session.execute(plan, confirmed=True, idempotency_key="verify-1")
    assert updates[-1].stage == "failed"

    with pytest.raises(InteractionError, match="refused to repeat"):
        session.execute(plan, confirmed=True, idempotency_key="verify-1")
    assert field.value == "Unexpected"


def test_full_preview_apply_progress_is_monotonic_and_truthful() -> None:
    class Indicator:
        def __init__(self) -> None:
            self.mouse: list[tuple[Bounds, str, bool]] = []
            self.carets: list[tuple[Bounds, str]] = []
            self.clear_count = 0

        def show_mouse(self, bounds: Bounds, label: str = "OpenWand", *, pulse: bool = False) -> None:
            self.mouse.append((bounds, label, pulse))

        def show_text_caret(self, bounds: Bounds, label: str = "OpenWand agent") -> None:
            self.carets.append((bounds, label))

        def clear(self) -> None:
            self.clear_count += 1

    toggle = _element("toggle-1", "Show hints", "checkbox", OperationType.TOGGLE)
    operation = SemanticOperation(
        "show-hints",
        OperationType.TOGGLE,
        toggle.locator(),
        {"state": True},
        reversible=True,
        rollback_limitations="Can be restored to its reviewed value.",
    )
    indicator = Indicator()
    session, updates = _session(FakeAccessibilityBackend((toggle,)), indicator=indicator)
    plan = _plan(operation)

    preview = session.prepare(plan)
    assert toggle.toggled is False
    assert preview.steps[0].target == "Show hints"
    assert preview.steps[0].requires_physical_input is False

    result = session.execute(plan, confirmed=True, idempotency_key="progress-1")

    assert result.status == "complete"
    assert toggle.toggled is True
    assert indicator.mouse == []
    assert indicator.carets == []
    assert indicator.clear_count == 3
    assert [update.stage for update in updates] == [
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


def test_text_value_operation_uses_agent_caret_not_mouse_indicator() -> None:
    class Indicator:
        def __init__(self) -> None:
            self.mouse_count = 0
            self.carets: list[tuple[Bounds, str]] = []

        def show_mouse(self, _bounds: Bounds, label: str = "OpenWand", *, pulse: bool = False) -> None:
            del label, pulse
            self.mouse_count += 1

        def show_text_caret(self, bounds: Bounds, label: str = "OpenWand agent") -> None:
            self.carets.append((bounds, label))

        def clear(self) -> None:
            return

    field = _element("field-1", "Display name", "edit", OperationType.SET_VALUE, value="Before")
    operation = SemanticOperation(
        "set-name",
        OperationType.SET_VALUE,
        field.locator(),
        {"value": "After"},
    )
    indicator = Indicator()
    session, _updates = _session(FakeAccessibilityBackend((field,)), indicator=indicator)
    plan = _plan(operation)
    session.prepare(plan)

    result = session.execute(plan, confirmed=True, idempotency_key="caret-1")

    assert result.status == "complete"
    assert indicator.mouse_count == 0
    assert [label for _bounds, label in indicator.carets] == ["OpenWand agent", "OpenWand agent"]


def test_bounded_inspector_redacts_editable_values() -> None:
    panel = _element("panel-1", "Settings", "pane", OperationType.INSPECT, ancestor_path=())
    field = _element(
        "field-1",
        "Private note",
        "edit",
        OperationType.SET_VALUE,
        ancestor_path=("Settings",),
        value="do not log this",
    )
    operation = SemanticOperation(
        "inspect",
        OperationType.INSPECT,
        panel.locator(),
        {"max_depth": 2, "max_nodes": 10},
    )
    driver = InteractionDriver((FakeAccessibilityBackend((panel, field)),))

    receipt = driver.execute(operation)

    assert len(receipt.output["elements"]) == 2
    assert receipt.output["elements"][1]["value"] == "<redacted>"
    assert "do not log this" not in repr(receipt.output)
