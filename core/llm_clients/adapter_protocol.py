"""Shared wire validation and errors for every model transport.

Provider responses are untrusted input. No parser repairs malformed arguments
into an executable call, and a failed continuation cannot replay executed work.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any


class AdapterProtocolError(ValueError):
    """A provider returned an unusable or ambiguous response."""


class AdapterCapabilityError(ValueError):
    """The selected transport cannot perform the requested operation."""


class ToolContinuationError(RuntimeError):
    """A turn failed after tools ran; route failover would risk repeating them."""

    tools_executed = True


def value(source, name: str, default=None):
    return source.get(name, default) if isinstance(source, dict) else getattr(source, name, default)


def snapshot(source) -> Any:
    if isinstance(source, dict):
        return {key: snapshot(item) for key, item in source.items()}
    if isinstance(source, (list, tuple)):
        return [snapshot(item) for item in source]
    dump = getattr(source, "model_dump", None)
    if callable(dump):
        return snapshot(dump(exclude_none=True))
    return deepcopy(source)


def _unique_object(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise AdapterProtocolError("Tool arguments contain duplicate object keys")
        result[key] = item
    return result


def json_object(arguments) -> dict[str, Any]:
    """Accept only finite JSON objects; preserve strings and Unicode exactly."""
    def invalid_constant(_constant):
        raise AdapterProtocolError("Tool arguments contain a non-finite number")

    try:
        if isinstance(arguments, dict):
            # Also validates SDK dictionaries, including nested NaN/Infinity.
            arguments = json.dumps(arguments, allow_nan=False)
        parsed = json.loads(
            "{}" if arguments is None or arguments == "" else arguments,
            object_pairs_hook=_unique_object, parse_constant=invalid_constant,
        )
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise AdapterProtocolError("Tool arguments must be a valid JSON object") from exc
    if not isinstance(parsed, dict):
        raise AdapterProtocolError("Tool arguments must be a JSON object")
    return parsed


def argument_error(arguments, schema: dict) -> str:
    """Validate arguments without allowing schema references to make requests."""
    from jsonschema.validators import validator_for
    from referencing import Registry
    from referencing.exceptions import NoSuchResource

    def no_remote(uri):
        raise NoSuchResource(ref=uri)

    if not isinstance(arguments, dict):
        return "Tool arguments must be a JSON object."
    try:
        json_object(arguments)
        validator = validator_for(schema)(schema, registry=Registry(retrieve=no_remote))
        if next(validator.iter_errors(arguments), None) is not None:
            return "Tool arguments do not match the offered JSON schema."
    except AdapterProtocolError as exc:
        return str(exc)
    except Exception:
        return "The offered tool schema could not be validated."
    return ""


def tool_call(call_id, name, arguments, *, provider_payload=None):
    from core.llm_clients.chat_tool_loop import OpenWandToolCall

    if not isinstance(call_id, str) or not call_id.strip():
        raise AdapterProtocolError("Provider tool call is missing a stable call ID")
    if not isinstance(name, str) or not name.strip():
        raise AdapterProtocolError("Provider tool call is missing a function name")
    error = ""
    try:
        parsed = json_object(arguments)
    except AdapterProtocolError as exc:
        parsed, error = {}, str(exc)
    return OpenWandToolCall(
        id=call_id, name=name, arguments=parsed,
        provider_payload=snapshot(provider_payload), validation_error=error,
    )


def validate_call_ids(calls, previous=()) -> None:
    seen = set(previous)
    for call in calls:
        if not isinstance(call.id, str) or not call.id.strip() or call.id in seen:
            raise AdapterProtocolError("Provider returned a missing or reused tool-call ID")
        seen.add(call.id)


def validate_results(pending, results) -> None:
    expected = {call.id: call.name for call in pending}
    actual = [result.call_id for result in results]
    if len(actual) != len(set(actual)) or set(actual) != set(expected):
        raise AdapterProtocolError("Tool results must match every pending call ID exactly once")
    if any(result.name != expected[result.call_id] for result in results):
        raise AdapterProtocolError("Tool result name does not match its call ID")


def result_text(content) -> str:
    return content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, allow_nan=False)


def check_terminal(reason: str | None, *, has_calls: bool = False) -> None:
    """Never execute calls from a truncated, refused, or interrupted turn."""
    if reason in {"length", "max_tokens", "incomplete", "max_output_tokens"}:
        raise AdapterProtocolError("Provider response was truncated before completion")
    if reason in {"content_filter", "refusal", "refused", "failed", "cancelled", "error"}:
        raise AdapterProtocolError(f"Provider response ended with {reason}")
    if reason in {"pause_turn", "in_progress", "queued"}:
        raise AdapterProtocolError("Provider response has not completed")
    if reason == "tool_calls" and not has_calls:
        raise AdapterProtocolError("Provider reported tool calls without any complete calls")
