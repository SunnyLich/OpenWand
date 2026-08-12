"""Safest-transport selection and deterministic semantic operation execution."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol

from core.actions.interaction.contracts import (
    ElementLocator,
    InteractionPlan,
    OperationReceipt,
    OperationType,
    SemanticOperation,
    StateCondition,
    StateField,
)


class InteractionError(RuntimeError):
    """Base error for safely refused interaction work."""


class ElementNotFoundError(InteractionError):
    """The exact recorded element no longer exists."""


class AmbiguousElementError(InteractionError):
    """More than one element matched a locator, so OpenWand refused to guess."""


class StaleElementError(InteractionError):
    """The resolved element has a different identity fingerprint."""


class PreconditionsChangedError(InteractionError):
    """Mutable state changed after preview and before Apply."""


class VerificationError(InteractionError):
    """The actual post-operation state did not match the exact postcondition."""


class UnsupportedOperationError(InteractionError):
    """No permitted transport can safely perform the requested operation."""


class TransportKind(StrEnum):
    """Transport order mirrors OpenWand's product safety hierarchy."""

    APPLICATION_API = "application_api"
    ACCESSIBILITY = "accessibility"
    BACKGROUND_WINDOW = "background_window"
    PHYSICAL_INPUT = "physical_input"


_TRANSPORT_PRIORITY = {
    TransportKind.APPLICATION_API: 10,
    TransportKind.ACCESSIBILITY: 20,
    TransportKind.BACKGROUND_WINDOW: 30,
    TransportKind.PHYSICAL_INPUT: 40,
}


class InteractionBackend(Protocol):
    """Narrow platform backend boundary used by the interaction driver."""

    transport: TransportKind

    def available(self) -> bool: ...

    def supports(self, operation_type: OperationType) -> bool: ...

    def resolve(self, locator: ElementLocator) -> Any: ...

    def can_perform(self, element: Any, operation_type: OperationType) -> bool: ...

    def read_state(self, element: Any) -> dict[str, Any]: ...

    def perform(self, operation: SemanticOperation, element: Any) -> dict[str, Any]: ...

    def inspect(self, locator: ElementLocator, *, max_depth: int, max_nodes: int) -> tuple[dict[str, Any], ...]: ...


class InteractionDriver:
    """Resolve every target afresh and use only an allow-listed safe transport."""

    def __init__(
        self,
        backends: tuple[InteractionBackend, ...],
        *,
        allow_physical_input: bool = False,
    ) -> None:
        self._backends = tuple(sorted(backends, key=lambda item: _TRANSPORT_PRIORITY[item.transport]))
        self.allow_physical_input = allow_physical_input

    def validate_plan(self, plan: InteractionPlan) -> None:
        seen_ids: set[str] = set()
        for operation in plan.operations:
            if operation.id in seen_ids:
                raise InteractionError(f"Duplicate operation ID: {operation.id}.")
            seen_ids.add(operation.id)
            if operation.target.application != plan.application or operation.target.window != plan.window:
                raise InteractionError(f"Operation {operation.id} targets a different application or window.")
            self._validate_args(operation)
            backend = self._choose_backend(operation.type)
            element = backend.resolve(operation.target)
            state = backend.read_state(element)
            if not backend.can_perform(element, operation.type):
                raise UnsupportedOperationError(
                    f"{operation.target.accessible_name!r} does not support {operation.type.value}."
                )
            if operation.type is OperationType.SET_VALUE and state.get("sensitive", False):
                raise UnsupportedOperationError(
                    "OpenWand does not enter credentials, payment data, or security codes."
                )
            if operation.type is not OperationType.INSPECT and not state.get(StateField.ENABLED.value, False):
                raise UnsupportedOperationError(f"{operation.target.accessible_name!r} is disabled.")
            self._check_conditions(operation.preconditions, state, precondition=True)

    def execute(self, operation: SemanticOperation) -> OperationReceipt:
        self._validate_args(operation)
        backend = self._choose_backend(operation.type)
        element = backend.resolve(operation.target)
        before = backend.read_state(element)
        if not backend.can_perform(element, operation.type):
            raise UnsupportedOperationError(
                f"{operation.target.accessible_name!r} does not support {operation.type.value}."
            )
        if operation.type is OperationType.SET_VALUE and before.get("sensitive", False):
            raise UnsupportedOperationError(
                "OpenWand does not enter credentials, payment data, or security codes."
            )
        self._check_conditions(operation.preconditions, before, precondition=True)

        if operation.type is OperationType.INSPECT:
            output = {
                "elements": backend.inspect(
                    operation.target,
                    max_depth=int(operation.args.get("max_depth", 4)),
                    max_nodes=int(operation.args.get("max_nodes", 100)),
                )
            }
            postconditions: tuple[StateCondition, ...] = ()
        else:
            output = backend.perform(operation, element)
            postconditions = self._postconditions(operation, before)

        after_element = backend.resolve(operation.target)
        after = backend.read_state(after_element)
        self._check_conditions(postconditions, after, precondition=False)
        return OperationReceipt(
            operation_id=operation.id,
            operation_type=operation.type.value,
            target=operation.target,
            transport=backend.transport.value,
            postconditions=postconditions,
            changed=before != after,
            output=output,
        )

    def transport_for(self, operation_type: OperationType) -> TransportKind:
        """Return the transport that would currently execute one registered operation."""
        return self._choose_backend(operation_type).transport

    def _choose_backend(self, operation_type: OperationType) -> InteractionBackend:
        for backend in self._backends:
            if backend.transport is TransportKind.PHYSICAL_INPUT and not self.allow_physical_input:
                continue
            if backend.available() and backend.supports(operation_type):
                return backend
        raise UnsupportedOperationError(f"No permitted transport supports {operation_type.value}.")

    @staticmethod
    def _check_conditions(
        conditions: tuple[StateCondition, ...],
        state: dict[str, Any],
        *,
        precondition: bool,
    ) -> None:
        for condition in conditions:
            actual = state.get(condition.field.value)
            if actual != condition.expected:
                error_type = PreconditionsChangedError if precondition else VerificationError
                phase = "precondition" if precondition else "postcondition"
                raise error_type(
                    f"Element {phase} failed for {condition.field.value}: "
                    f"expected {condition.expected!r}, found {actual!r}."
                )

    @staticmethod
    def _postconditions(
        operation: SemanticOperation,
        before: dict[str, Any],
    ) -> tuple[StateCondition, ...]:
        if operation.postconditions:
            return operation.postconditions
        if operation.type is OperationType.SET_VALUE:
            return (StateCondition(StateField.VALUE, operation.args["value"]),)
        if operation.type is OperationType.TOGGLE:
            return (StateCondition(StateField.TOGGLED, operation.args["state"]),)
        if operation.type is OperationType.SELECT:
            return (StateCondition(StateField.SELECTED, True),)
        if operation.type is OperationType.SCROLL:
            expected = int(before.get(StateField.SCROLL_OFFSET.value, 0)) + int(operation.args["amount"])
            return (StateCondition(StateField.SCROLL_OFFSET, expected),)
        if operation.type is OperationType.INVOKE:
            expected = int(before.get(StateField.INVOCATION_COUNT.value, 0)) + 1
            return (StateCondition(StateField.INVOCATION_COUNT, expected),)
        return ()

    @staticmethod
    def _validate_args(operation: SemanticOperation) -> None:
        args = operation.args
        expected_fields: dict[OperationType, set[str]] = {
            OperationType.INSPECT: {"max_depth", "max_nodes"},
            OperationType.INVOKE: set(),
            OperationType.SET_VALUE: {"value"},
            OperationType.TOGGLE: {"state"},
            OperationType.SELECT: set(),
            OperationType.SCROLL: {"amount"},
        }
        unknown = set(args) - expected_fields[operation.type]
        if unknown:
            raise InteractionError(f"Unsupported arguments for {operation.type.value}: {sorted(unknown)}.")
        if operation.type is OperationType.SET_VALUE:
            if not isinstance(args.get("value"), str):
                raise InteractionError("set_value requires one string value.")
            sensitive_tokens = ("password", "passcode", "security code", "payment", "credit card", "cvv")
            label = operation.target.accessible_name.casefold()
            if any(token in label for token in sensitive_tokens):
                raise UnsupportedOperationError("OpenWand does not enter credentials, payment data, or security codes.")
        elif operation.type is OperationType.TOGGLE and not isinstance(args.get("state"), bool):
            raise InteractionError("toggle requires an exact boolean state.")
        elif operation.type is OperationType.SCROLL:
            amount = args.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount == 0 or not -3 <= amount <= 3:
                raise InteractionError("scroll amount must be a non-zero integer from -3 to 3.")
        elif operation.type is OperationType.INSPECT:
            max_depth = args.get("max_depth", 4)
            max_nodes = args.get("max_nodes", 100)
            if not isinstance(max_depth, int) or not 0 <= max_depth <= 12:
                raise InteractionError("inspect max_depth must be from 0 to 12.")
            if not isinstance(max_nodes, int) or not 1 <= max_nodes <= 500:
                raise InteractionError("inspect max_nodes must be from 1 to 500.")
