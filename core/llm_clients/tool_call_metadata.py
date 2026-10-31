"""Preserve opaque provider metadata and stable identities in tool-call replay."""
from __future__ import annotations

from copy import deepcopy


def _value(source, name):
    return source.get(name) if isinstance(source, dict) else getattr(source, name, None)


def _merge_metadata(target: dict, source: dict) -> None:
    """Merge metadata fragments without concatenating signatures or erasing values."""
    for key, value in source.items():
        if value is None:
            continue
        if isinstance(value, dict):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            _merge_metadata(target[key], value)
        else:
            target[key] = deepcopy(value)


def copy_tool_call_metadata(source, target: dict) -> None:
    """Copy SDK extensions, including Google's thought_signature, into a call."""
    extra = _value(source, "extra_content")
    if isinstance(extra, dict) and extra:
        metadata = target.setdefault("extra_content", {})
        _merge_metadata(metadata, extra)


def tool_call_payload(call: dict) -> dict:
    """Serialize a normalized call without sharing mutable provider metadata."""
    payload = {
        "id": call["id"],
        "type": "function",
        "function": {"name": call["name"], "arguments": call["arguments"]},
    }
    copy_tool_call_metadata(call, payload)
    return payload


class StreamToolCallAccumulator:
    """Join text fragments by index or ID while retaining per-call metadata."""

    def __init__(self):
        self.calls: dict[int, dict] = {}
        self._indices: dict[int, int] = {}
        self._ids: dict[str, int] = {}

    def add(self, fragment) -> None:
        """Accumulate a delta, rejecting ambiguous identity before changing state."""
        index = _value(fragment, "index")
        call_id = _value(fragment, "id")
        if index is not None and (type(index) is not int or index < 0):
            raise ValueError("Tool-call fragment has an invalid index")
        if call_id is not None and (not isinstance(call_id, str) or (call_id and not call_id.strip())):
            raise ValueError("Tool-call fragment has an invalid ID")
        call_id = call_id or None
        if index is None and call_id is None:
            function = _value(fragment, "function")
            if (
                not _value(function, "name")
                and not _value(function, "arguments")
                and not _value(fragment, "extra_content")
            ):
                return
            raise ValueError("Tool-call fragment has no index or ID")

        by_index = self._indices.get(index) if index is not None else None
        by_id = self._ids.get(call_id) if call_id is not None else None
        if by_index is not None and by_id is not None and by_index != by_id:
            raise ValueError("Tool-call fragment identifies different calls")
        key = by_index if by_index is not None else by_id
        if key is not None:
            existing_id = self.calls[key]["id"]
            if call_id is not None and existing_id and existing_id != call_id:
                raise ValueError("Tool-call fragment changes an existing call ID")
            if index is not None and by_index is None and key in self._indices.values():
                raise ValueError("Tool-call fragment changes an existing call index")
        else:
            key = len(self.calls)
            self.calls[key] = {"id": "", "name": "", "arguments": ""}

        entry = self.calls[key]
        if index is not None:
            self._indices[index] = key
        if call_id is not None:
            self._ids[call_id] = key
            entry["id"] = call_id
        function = _value(fragment, "function")
        if function is not None:
            entry["name"] += _value(function, "name") or ""
            entry["arguments"] += _value(function, "arguments") or ""
        copy_tool_call_metadata(fragment, entry)
