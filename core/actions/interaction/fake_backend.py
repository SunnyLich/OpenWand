"""Deterministic fake accessibility tree for safe interaction-driver tests."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from core.actions.interaction.contracts import (
    ApplicationIdentity,
    Bounds,
    ElementLocator,
    OperationType,
    SemanticOperation,
    WindowIdentity,
)
from core.actions.interaction.driver import (
    AmbiguousElementError,
    ElementNotFoundError,
    StaleElementError,
    TransportKind,
    UnsupportedOperationError,
)


@dataclass(slots=True)
class FakeElement:
    """One element in a flat, ancestry-labelled fake accessibility tree."""

    element_id: str
    application: ApplicationIdentity
    window: WindowIdentity
    role: str
    accessible_name: str
    automation_id: str = ""
    ancestor_path: tuple[str, ...] = ()
    bounds: Bounds = field(default_factory=lambda: Bounds(0, 0, 100, 30))
    supported_operations: frozenset[OperationType] = field(default_factory=frozenset)
    value: str = ""
    enabled: bool = True
    toggled: bool = False
    selected: bool = False
    scroll_offset: int = 0
    invocation_count: int = 0
    sensitive: bool = False

    @property
    def fingerprint(self) -> str:
        """Fingerprint semantic identity, deliberately excluding mutable state and bounds."""
        payload = {
            "element_id": self.element_id,
            "app": self.application.app_id,
            "process_id": self.application.process_id,
            "window_id": self.window.window_id,
            "role": self.role,
            "name": self.accessible_name,
            "automation_id": self.automation_id,
            "ancestor_path": self.ancestor_path,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def locator(self) -> ElementLocator:
        return ElementLocator(
            application=self.application,
            window=self.window,
            role=self.role,
            accessible_name=self.accessible_name,
            automation_id=self.automation_id,
            ancestor_path=self.ancestor_path,
            snapshot_fingerprint=self.fingerprint,
            bounds=self.bounds,
        )


AfterExecuteHook = Callable[[SemanticOperation, FakeElement], None]


class FakeAccessibilityBackend:
    """In-memory accessibility backend with the same refusal behavior as native backends."""

    transport = TransportKind.ACCESSIBILITY

    def __init__(
        self,
        elements: Iterable[FakeElement],
        *,
        after_execute: AfterExecuteHook | None = None,
    ) -> None:
        self.elements = list(elements)
        self.after_execute = after_execute

    def available(self) -> bool:
        return True

    def supports(self, operation_type: OperationType) -> bool:
        return any(operation_type in element.supported_operations for element in self.elements)

    @staticmethod
    def can_perform(element: FakeElement, operation_type: OperationType) -> bool:
        return operation_type in element.supported_operations

    def resolve(self, locator: ElementLocator) -> FakeElement:
        matches = [
            element
            for element in self.elements
            if element.application == locator.application
            and element.window == locator.window
            and element.role == locator.role
            and (not locator.accessible_name or element.accessible_name == locator.accessible_name)
            and (not locator.automation_id or element.automation_id == locator.automation_id)
            and element.ancestor_path == locator.ancestor_path
        ]
        if not matches:
            raise ElementNotFoundError("The recorded semantic element no longer exists.")
        if len(matches) > 1:
            raise AmbiguousElementError("The semantic locator matched more than one element; OpenWand refused to guess.")
        element = matches[0]
        if element.fingerprint != locator.snapshot_fingerprint:
            raise StaleElementError("The semantic element identity changed after the preview.")
        return element

    @staticmethod
    def read_state(element: FakeElement) -> dict[str, Any]:
        return {
            "value": element.value,
            "enabled": element.enabled,
            "toggled": element.toggled,
            "selected": element.selected,
            "scroll_offset": element.scroll_offset,
            "invocation_count": element.invocation_count,
            "sensitive": element.sensitive,
        }

    def perform(self, operation: SemanticOperation, element: FakeElement) -> dict[str, Any]:
        if operation.type not in element.supported_operations:
            raise UnsupportedOperationError(
                f"{element.accessible_name!r} does not support {operation.type.value}."
            )
        if not element.enabled:
            raise UnsupportedOperationError(f"{element.accessible_name!r} is disabled.")

        if operation.type is OperationType.INVOKE:
            element.invocation_count += 1
        elif operation.type is OperationType.SET_VALUE:
            element.value = operation.args["value"]
        elif operation.type is OperationType.TOGGLE:
            element.toggled = operation.args["state"]
        elif operation.type is OperationType.SELECT:
            element.selected = True
        elif operation.type is OperationType.SCROLL:
            element.scroll_offset += operation.args["amount"]
        else:
            raise UnsupportedOperationError(f"The fake backend cannot mutate through {operation.type.value}.")

        if self.after_execute is not None:
            self.after_execute(operation, element)
        return {"element_id": element.element_id}

    def inspect(
        self,
        locator: ElementLocator,
        *,
        max_depth: int,
        max_nodes: int,
    ) -> tuple[dict[str, Any], ...]:
        root = self.resolve(locator)
        root_depth = len(root.ancestor_path)
        prefix = (*root.ancestor_path, root.accessible_name)
        candidates = [
            element
            for element in self.elements
            if element.application == root.application
            and element.window == root.window
            and (
                element is root
                or (
                    element.ancestor_path[: len(prefix)] == prefix
                    and len(element.ancestor_path) - root_depth <= max_depth
                )
            )
        ]
        snapshot = []
        for element in candidates[:max_nodes]:
            snapshot.append(
                {
                    "role": element.role,
                    "name": element.accessible_name,
                    "automation_id": element.automation_id,
                    "ancestor_path": element.ancestor_path,
                    "bounds": {
                        "x": element.bounds.x,
                        "y": element.bounds.y,
                        "width": element.bounds.width,
                        "height": element.bounds.height,
                    },
                    "value": "<redacted>" if element.sensitive or element.role in {"edit", "text_field"} else element.value,
                    "capabilities": tuple(sorted(item.value for item in element.supported_operations)),
                    "fingerprint": element.fingerprint,
                }
            )
        return tuple(snapshot)
