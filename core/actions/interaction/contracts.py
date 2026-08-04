"""Versioned, serializable contracts for semantic application interaction."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

CONTRACT_VERSION = 1


class OperationType(StrEnum):
    """The deliberately small operation allow-list for the first slice."""

    INSPECT = "interaction.inspect@1"
    INVOKE = "interaction.invoke@1"
    SET_VALUE = "interaction.set_value@1"
    TOGGLE = "interaction.toggle@1"
    SELECT = "interaction.select@1"
    SCROLL = "interaction.scroll@1"


class StateField(StrEnum):
    """Element state that deterministic pre/postconditions may inspect."""

    VALUE = "value"
    ENABLED = "enabled"
    TOGGLED = "toggled"
    SELECTED = "selected"
    SCROLL_OFFSET = "scroll_offset"
    INVOCATION_COUNT = "invocation_count"


@dataclass(frozen=True, slots=True)
class Bounds:
    """Screen bounds used for verification and the ghost cursor, never targeting."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("element bounds cannot have a negative size")

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ApplicationIdentity:
    """Stable evidence identifying the target application process."""

    app_id: str
    process_id: int = 0
    executable: str = ""


@dataclass(frozen=True, slots=True)
class WindowIdentity:
    """Stable evidence identifying the exact target window."""

    window_id: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class ElementLocator:
    """Semantic locator produced from a previously inspected element snapshot."""

    application: ApplicationIdentity
    window: WindowIdentity
    role: str
    accessible_name: str = ""
    automation_id: str = ""
    ancestor_path: tuple[str, ...] = ()
    snapshot_fingerprint: str = ""
    bounds: Bounds | None = None
    schema_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported locator schema version: {self.schema_version}")
        if not self.application.app_id.strip() or not self.window.window_id.strip() or not self.role.strip():
            raise ValueError("locator requires application, window, and role identity")
        if not self.accessible_name.strip() and not self.automation_id.strip():
            raise ValueError("locator requires an accessible name or automation identifier")
        if not self.snapshot_fingerprint.strip():
            raise ValueError("locator requires a snapshot fingerprint")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class StateCondition:
    """An exact condition over a registered, non-arbitrary state field."""

    field: StateField
    expected: Any


@dataclass(frozen=True, slots=True)
class SemanticOperation:
    """One registered semantic operation; no coordinates or key streams allowed."""

    id: str
    type: OperationType
    target: ElementLocator
    args: dict[str, Any] = field(default_factory=dict)
    preconditions: tuple[StateCondition, ...] = ()
    postconditions: tuple[StateCondition, ...] = ()
    requires_focus: bool = False
    reversible: bool = False
    rollback_limitations: str = "Cannot be rolled back automatically."
    schema_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported operation schema version: {self.schema_version}")
        if not self.id.strip():
            raise ValueError("operation ID is required")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["type"] = self.type.value
        return value


@dataclass(frozen=True, slots=True)
class InteractionPlan:
    """The exact typed plan shared by preview and execution."""

    plan_id: str
    application: ApplicationIdentity
    window: WindowIdentity
    summary: str
    operations: tuple[SemanticOperation, ...]
    requires_confirmation: bool = True
    schema_version: int = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CONTRACT_VERSION:
            raise ValueError(f"unsupported interaction plan schema version: {self.schema_version}")
        if not self.plan_id.strip() or not self.operations:
            raise ValueError("interaction plan requires an ID and at least one operation")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for operation in value["operations"]:
            operation["type"] = str(operation["type"])
        return value


@dataclass(frozen=True, slots=True)
class PreviewStep:
    """One human-reviewable step derived directly from a semantic operation."""

    operation_id: str
    operation_type: str
    target: str
    changes: tuple[str, ...]
    requires_focus: bool
    requires_physical_input: bool
    rollback: str


@dataclass(frozen=True, slots=True)
class InteractionPreview:
    """Exact preview of an interaction plan with no separately interpreted prose."""

    plan_id: str
    application: str
    window: str
    summary: str
    steps: tuple[PreviewStep, ...]


@dataclass(frozen=True, slots=True)
class OperationReceipt:
    """Evidence retained after one operation for deterministic verification."""

    operation_id: str
    operation_type: str
    target: ElementLocator
    transport: str
    postconditions: tuple[StateCondition, ...]
    changed: bool
    output: dict[str, Any] = field(default_factory=dict)
