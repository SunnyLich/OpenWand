"""Action-platform errors with user-displayable validation details."""

from __future__ import annotations

from core.actions.contracts import ValidationIssue


class ActionValidationError(ValueError):
    """Raised when a plan is unsafe or unsupported for the current target."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        message = "; ".join(issue.message for issue in issues) or "Action validation failed."
        super().__init__(message)


class ActionUnavailableError(RuntimeError):
    """Raised when a supported app or target is not currently available."""
