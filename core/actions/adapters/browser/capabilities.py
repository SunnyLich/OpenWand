"""Capabilities exposed by OpenWand's managed browser adapter."""

from core.actions.contracts import ActionCapability, ActionRisk

FILL_FORM = "browser.fill_form"


def browser_capabilities() -> tuple[ActionCapability, ...]:
    return (
        ActionCapability(
            type=FILL_FORM,
            app="browser",
            title="Fill web form",
            description="Fill reviewed values into existing non-password form fields without submitting.",
            input_schema={
                "type": "object",
                "properties": {
                    "assignments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field_id": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["field_id", "value"],
                            "additionalProperties": False,
                        },
                        "maxItems": 20,
                    }
                },
                "required": ["assignments"],
                "additionalProperties": False,
            },
            risk=ActionRisk.MEDIUM,
            reversible=True,
        ),
    )
