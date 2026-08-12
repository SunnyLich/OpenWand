"""Tests for focusless Windows UI Automation interaction semantics."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.actions.interaction import InteractionDriver, OperationType, SemanticOperation, StateCondition, StateField
from core.actions.interaction.driver import StaleElementError, UnsupportedOperationError
from core.actions.interaction.windows_uia import WindowsUIAutomationBackend


class FakeCollection:
    def __init__(self, elements) -> None:
        self.elements = list(elements)
        self.Length = len(self.elements)

    def GetElement(self, index: int):
        return self.elements[index]


class FakeValuePattern:
    def __init__(self, value: str, *, read_only: bool = False) -> None:
        self.CurrentValue = value
        self.CurrentIsReadOnly = read_only

    def QueryInterface(self, _interface):
        return self

    def SetValue(self, value: str) -> None:
        self.CurrentValue = value


class FakeTogglePattern:
    def __init__(self, state: bool = False) -> None:
        self.CurrentToggleState = 1 if state else 0

    def QueryInterface(self, _interface):
        return self

    def Toggle(self) -> None:
        self.CurrentToggleState = 0 if self.CurrentToggleState == 1 else 1


class FakeSelectionPattern:
    def __init__(self, selected: bool = False) -> None:
        self.CurrentIsSelected = selected

    def QueryInterface(self, _interface):
        return self

    def Select(self) -> None:
        self.CurrentIsSelected = True


class FakeElement:
    def __init__(
        self,
        *,
        runtime_id: int,
        name: str,
        automation_id: str,
        control_type: int,
        patterns: dict[int, object] | None = None,
        sensitive: bool = False,
    ) -> None:
        self.runtime_id = runtime_id
        self.CurrentName = name
        self.CurrentAutomationId = automation_id
        self.CurrentControlType = control_type
        self.CurrentProcessId = 42
        self.CurrentBoundingRectangle = (100, 120, 360, 152)
        self.CurrentIsEnabled = True
        self.CurrentIsPassword = sensitive
        self.patterns = patterns or {}
        self.descendants: list[FakeElement] = []

    def GetRuntimeId(self):
        return (42, self.runtime_id)

    def GetCurrentPattern(self, pattern_id: int):
        if pattern_id not in self.patterns:
            raise LookupError(pattern_id)
        return self.patterns[pattern_id]

    def FindAll(self, _scope: int, _condition):
        return FakeCollection(self.descendants)

    def SetFocus(self) -> None:
        raise AssertionError("The semantic backend must never take focus")


class FakeWalker:
    def __init__(self, parents: dict[FakeElement, FakeElement]) -> None:
        self.parents = parents

    def GetParentElement(self, element: FakeElement):
        return self.parents.get(element)


class FakeUia:
    def __init__(self, root: FakeElement, parents: dict[FakeElement, FakeElement]) -> None:
        self.root = root
        self.ControlViewWalker = FakeWalker(parents)
        self.element_from_handle_calls: list[int] = []

    def ElementFromHandle(self, window_id: int):
        self.element_from_handle_calls.append(window_id)
        return self.root

    @staticmethod
    def CreateTrueCondition():
        return object()


UIAC = SimpleNamespace(
    IUIAutomationValuePattern=object(),
    IUIAutomationTogglePattern=object(),
    IUIAutomationSelectionItemPattern=object(),
)


def _backend(*children: FakeElement):
    root = FakeElement(runtime_id=1, name="OpenWand test form", automation_id="window", control_type=50032)
    root.descendants = list(children)
    uia = FakeUia(root, {child: root for child in children})
    return WindowsUIAutomationBackend(uia=uia, uiac=UIAC, mutation_process_ids={42}), root, uia


def test_inspector_is_bounded_redacted_and_reports_real_patterns() -> None:
    value = FakeValuePattern("private draft")
    field = FakeElement(
        runtime_id=2,
        name="Display name",
        automation_id="display-name",
        control_type=50004,
        patterns={10002: value},
    )
    backend, _root, uia = _backend(field)

    snapshots = backend.inspect_window(777, max_nodes=10)

    assert uia.element_from_handle_calls == [777]
    assert len(snapshots) == 2
    editable = snapshots[1]
    assert editable["value"] == "<redacted>"
    assert editable["bounds"] == {"x": 100, "y": 120, "width": 260, "height": 32}
    assert OperationType.SET_VALUE.value in editable["capabilities"]


def test_value_pattern_updates_without_focus_or_keystrokes() -> None:
    value = FakeValuePattern("Before")
    field = FakeElement(
        runtime_id=2,
        name="Display name",
        automation_id="display-name",
        control_type=50004,
        patterns={10002: value},
    )
    backend, _root, _uia = _backend(field)
    locator = backend.inspect_window(777)[1]["locator"]
    operation = SemanticOperation(
        "set-name",
        OperationType.SET_VALUE,
        locator,
        {"value": "After"},
        preconditions=(StateCondition(StateField.VALUE, "Before"),),
    )

    receipt = InteractionDriver((backend,)).execute(operation)

    assert value.CurrentValue == "After"
    assert receipt.transport == "accessibility"
    assert receipt.output == {"semantic_method": "ValuePattern.SetValue"}


def test_toggle_and_selection_set_exact_states() -> None:
    toggle_pattern = FakeTogglePattern(False)
    selection_pattern = FakeSelectionPattern(False)
    toggle = FakeElement(
        runtime_id=2,
        name="Show hints",
        automation_id="show-hints",
        control_type=50002,
        patterns={10015: toggle_pattern},
    )
    item = FakeElement(
        runtime_id=3,
        name="Purple",
        automation_id="purple",
        control_type=50007,
        patterns={10010: selection_pattern},
    )
    backend, _root, _uia = _backend(toggle, item)
    snapshots = backend.inspect_window(777)
    driver = InteractionDriver((backend,))

    driver.execute(SemanticOperation("toggle", OperationType.TOGGLE, snapshots[1]["locator"], {"state": True}))
    driver.execute(SemanticOperation("select", OperationType.SELECT, snapshots[2]["locator"]))

    assert toggle_pattern.CurrentToggleState == 1
    assert selection_pattern.CurrentIsSelected is True


def test_replaced_runtime_identity_is_stale() -> None:
    field = FakeElement(
        runtime_id=2,
        name="Display name",
        automation_id="display-name",
        control_type=50004,
        patterns={10002: FakeValuePattern("Before")},
    )
    backend, _root, _uia = _backend(field)
    locator = backend.inspect_window(777)[1]["locator"]

    field.runtime_id = 99

    with pytest.raises(StaleElementError, match="identity changed"):
        backend.resolve(locator)


def test_invoke_is_refused_until_a_workflow_has_observable_verification() -> None:
    button = FakeElement(
        runtime_id=2,
        name="Save",
        automation_id="save",
        control_type=50000,
    )
    backend, _root, _uia = _backend(button)
    locator = backend.inspect_window(777)[1]["locator"]

    with pytest.raises(UnsupportedOperationError, match="No permitted transport"):
        InteractionDriver((backend,)).execute(SemanticOperation("save", OperationType.INVOKE, locator))


def test_native_mutation_is_disabled_until_the_exact_process_is_allowlisted() -> None:
    value = FakeValuePattern("Before")
    field = FakeElement(
        runtime_id=2,
        name="Display name",
        automation_id="display-name",
        control_type=50004,
        patterns={10002: value},
    )
    root = FakeElement(runtime_id=1, name="OpenWand test form", automation_id="window", control_type=50032)
    root.descendants = [field]
    backend = WindowsUIAutomationBackend(
        uia=FakeUia(root, {field: root}),
        uiac=UIAC,
    )
    locator = backend.inspect_window(777)[1]["locator"]

    with pytest.raises(UnsupportedOperationError, match="does not support"):
        InteractionDriver((backend,)).execute(
            SemanticOperation("set-name", OperationType.SET_VALUE, locator, {"value": "After"})
        )
    assert value.CurrentValue == "Before"
