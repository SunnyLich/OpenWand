"""Platform-neutral semantic interaction contracts and deterministic executor."""

from core.actions.interaction.contracts import (
    ApplicationIdentity,
    Bounds,
    ElementLocator,
    InteractionPlan,
    InteractionPreview,
    OperationReceipt,
    OperationType,
    SemanticOperation,
    StateCondition,
    StateField,
    WindowIdentity,
)
from core.actions.interaction.driver import InteractionDriver, TransportKind
from core.actions.interaction.fake_backend import FakeAccessibilityBackend, FakeElement
from core.actions.interaction.session import CancellationToken, InteractionSession, SessionResult
from core.actions.interaction.windows_uia import WindowsUIAutomationBackend

__all__ = [
    "ApplicationIdentity",
    "Bounds",
    "CancellationToken",
    "ElementLocator",
    "FakeAccessibilityBackend",
    "FakeElement",
    "InteractionDriver",
    "InteractionPlan",
    "InteractionPreview",
    "InteractionSession",
    "OperationReceipt",
    "OperationType",
    "SemanticOperation",
    "SessionResult",
    "StateCondition",
    "StateField",
    "TransportKind",
    "WindowIdentity",
    "WindowsUIAutomationBackend",
]
