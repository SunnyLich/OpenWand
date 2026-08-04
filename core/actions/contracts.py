"""Serializable contracts shared by action planners, previews, and adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ActionRisk(StrEnum):
    """Risk assigned by Wisp code, never by model prose."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ActionTarget:
    """Identity and freshness token for the object an action will change."""

    app: str
    display_name: str
    locator: dict[str, str]
    version: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible target."""
        return asdict(self)


@dataclass(frozen=True)
class ActionOperation:
    """One versioned operation in a dependency-ordered action plan."""

    id: str
    type: str
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible operation."""
        return asdict(self)


@dataclass(frozen=True)
class ActionPlan:
    """The exact plan consumed by both preview and execution."""

    plan_id: str
    app: str
    target: ActionTarget
    summary: str
    operations: tuple[ActionOperation, ...]
    risk: ActionRisk
    requires_confirmation: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible plan for IPC and persistence."""
        value = asdict(self)
        value["risk"] = self.risk.value
        return value


@dataclass(frozen=True)
class ActionCapability:
    """A registered operation that a planner is allowed to request."""

    type: str
    app: str
    title: str
    description: str
    input_schema: dict[str, Any]
    risk: ActionRisk
    reversible: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible capability."""
        value = asdict(self)
        value["risk"] = self.risk.value
        return value


@dataclass(frozen=True)
class ValidationIssue:
    """A deterministic validation failure suitable for the preview UI."""

    code: str
    message: str
    operation_id: str = ""


@dataclass(frozen=True)
class ActionPreview:
    """Structured and HTML forms of a preview for one exact plan."""

    plan_id: str
    title: str
    summary: str
    html: str
    details: tuple[dict[str, Any], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionExecutionResult:
    """Verified result returned after an adapter executes a confirmed plan."""

    plan_id: str
    status: str
    message: str
    created: tuple[dict[str, str], ...] = ()
    journal: tuple[dict[str, Any], ...] = ()
    verification: tuple[str, ...] = ()
