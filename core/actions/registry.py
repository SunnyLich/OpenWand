"""Capability registry and app-independent structural plan validation."""

from __future__ import annotations

import re
from collections.abc import Iterable

from core.actions.contracts import ActionCapability, ActionPlan, ValidationIssue

_OPERATION_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_ACTION_TYPE = re.compile(r"^[a-z][a-z0-9_-]*\.[a-z][a-z0-9_-]*@[1-9][0-9]*$")


class ActionRegistry:
    """The allow-list of action types available to planners and executors."""

    def __init__(self, capabilities: Iterable[ActionCapability] = ()) -> None:
        self._capabilities: dict[str, ActionCapability] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: ActionCapability) -> None:
        """Register one versioned capability, rejecting ambiguous duplicates."""
        if not _ACTION_TYPE.fullmatch(capability.type):
            raise ValueError(f"invalid action type: {capability.type!r}")
        if capability.type in self._capabilities:
            raise ValueError(f"action type is already registered: {capability.type}")
        self._capabilities[capability.type] = capability

    def get(self, action_type: str) -> ActionCapability | None:
        """Return one capability by its exact versioned type."""
        return self._capabilities.get(action_type)

    def capabilities_for(self, app: str) -> tuple[ActionCapability, ...]:
        """Return the stable, sorted capability set for an app."""
        return tuple(
            capability
            for _name, capability in sorted(self._capabilities.items())
            if capability.app == app
        )

    def validate_plan(self, plan: ActionPlan) -> tuple[ValidationIssue, ...]:
        """Validate plan structure and capability schemas without touching an app."""
        issues: list[ValidationIssue] = []
        if plan.app != plan.target.app:
            issues.append(ValidationIssue("target_app_mismatch", "The plan and target name different apps."))
        if not plan.operations:
            issues.append(ValidationIssue("empty_plan", "The plan contains no operations."))
            return tuple(issues)

        operation_ids: set[str] = set()
        for operation in plan.operations:
            if not _OPERATION_ID.fullmatch(operation.id):
                issues.append(
                    ValidationIssue("invalid_operation_id", f"Invalid operation ID: {operation.id!r}.", operation.id)
                )
            elif operation.id in operation_ids:
                issues.append(
                    ValidationIssue("duplicate_operation_id", f"Duplicate operation ID: {operation.id!r}.", operation.id)
                )
            operation_ids.add(operation.id)

            capability = self.get(operation.type)
            if capability is None:
                issues.append(
                    ValidationIssue("unsupported_action", f"Unsupported action type: {operation.type}.", operation.id)
                )
                continue
            if capability.app != plan.app:
                issues.append(
                    ValidationIssue(
                        "capability_app_mismatch",
                        f"{operation.type} cannot run in {plan.app}.",
                        operation.id,
                    )
                )
                continue
            issues.extend(self._validate_args(operation.id, operation.args, capability.input_schema))

        for operation in plan.operations:
            for dependency in operation.depends_on:
                if dependency == operation.id:
                    issues.append(
                        ValidationIssue("self_dependency", "An operation cannot depend on itself.", operation.id)
                    )
                elif dependency not in operation_ids:
                    issues.append(
                        ValidationIssue(
                            "missing_dependency",
                            f"Operation depends on missing operation {dependency!r}.",
                            operation.id,
                        )
                    )
        return tuple(issues)

    @staticmethod
    def _validate_args(
        operation_id: str,
        args: dict[str, object],
        schema: dict[str, object],
    ) -> list[ValidationIssue]:
        """Validate the deliberately small JSON Schema subset used by actions."""
        issues: list[ValidationIssue] = []
        properties = schema.get("properties")
        declared = properties if isinstance(properties, dict) else {}
        required = schema.get("required")
        for field in required if isinstance(required, list) else []:
            if isinstance(field, str) and field not in args:
                issues.append(
                    ValidationIssue("missing_argument", f"Missing required argument {field!r}.", operation_id)
                )

        if schema.get("additionalProperties") is False:
            for field in args:
                if field not in declared:
                    issues.append(
                        ValidationIssue("unknown_argument", f"Unknown argument {field!r}.", operation_id)
                    )

        for field, value in args.items():
            field_schema = declared.get(field)
            if not isinstance(field_schema, dict):
                continue
            expected = field_schema.get("type")
            if expected == "string" and not isinstance(value, str):
                issues.append(ValidationIssue("argument_type", f"{field!r} must be a string.", operation_id))
            elif expected == "boolean" and not isinstance(value, bool):
                issues.append(ValidationIssue("argument_type", f"{field!r} must be a boolean.", operation_id))
            elif expected == "number" and (isinstance(value, bool) or not isinstance(value, int | float)):
                issues.append(ValidationIssue("argument_type", f"{field!r} must be a number.", operation_id))
            choices = field_schema.get("enum")
            if isinstance(choices, list) and value not in choices:
                issues.append(
                    ValidationIssue(
                        "argument_choice",
                        f"{field!r} must be one of: {', '.join(map(str, choices))}.",
                        operation_id,
                    )
                )
        return issues
