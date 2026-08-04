"""Versioned VS Code capabilities implemented by Wisp."""

from __future__ import annotations

from core.actions.contracts import ActionCapability, ActionRisk

REPLACE_SELECTION = "vscode.replace_selection@1"
REPLACE_FILE = "vscode.replace_file@1"


def vscode_capabilities() -> tuple[ActionCapability, ...]:
    """Return the first safe editor operation available to the planner."""
    return (
        ActionCapability(
            type=REPLACE_SELECTION,
            app="vscode",
            title="Fix selected code",
            description="Replace one uniquely selected block in the active saved file.",
            input_schema={
                "type": "object",
                "required": [
                    "start",
                    "end",
                    "expected_selection_sha256",
                    "replacement_text",
                ],
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "expected_selection_sha256": {"type": "string"},
                    "replacement_text": {"type": "string"},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
        ActionCapability(
            type=REPLACE_FILE,
            app="vscode",
            title="Fill empty saved file",
            description="Fill the exact active empty saved file without focusing VS Code.",
            input_schema={
                "type": "object",
                "required": ["expected_file_sha256", "replacement_text"],
                "properties": {
                    "expected_file_sha256": {"type": "string"},
                    "replacement_text": {"type": "string"},
                },
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )
