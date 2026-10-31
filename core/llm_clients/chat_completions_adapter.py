"""One Chat Completions tool adapter for all compatible providers.

Streaming and complete replies use the same decoder on every turn. Provider
reasoning/signatures stay in the transcript, separate from user-visible text.
"""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy

from core.llm_clients.adapter_protocol import (
    AdapterProtocolError,
    check_terminal,
    result_text,
    snapshot,
    tool_call,
    validate_call_ids,
    validate_results,
    value,
)
from core.llm_clients.chat_tool_loop import ChatModelTurn
from core.llm_clients.tool_call_metadata import StreamToolCallAccumulator, copy_tool_call_metadata, tool_call_payload


def complete_calls(message) -> dict[int, dict]:
    calls = {}
    for index, item in enumerate(value(message, "tool_calls", []) or []):
        if value(item, "type", "function") != "function":
            raise AdapterProtocolError("Provider returned an unsupported tool-call type")
        function = value(item, "function", {})
        entry = {
            "id": value(item, "id", ""), "name": value(function, "name", ""),
            "arguments": value(function, "arguments", ""),
        }
        copy_tool_call_metadata(item, entry)
        calls[index] = entry
    return calls


def text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(value(part, "text", "") or "") for part in content)
    return ""


class ChatCompletionsLoopModel:
    def __init__(self, client, *, provider: str, model: str, kwargs: dict):
        self.client, self.provider, self.model = client, provider, model
        self.options = deepcopy(kwargs)
        self.stream_first = bool(self.options.get("stream", True))
        self.messages = self.options.pop("messages")
        self.options.pop("stream", None)
        self.pending = []
        self.sent = 0
        self.turn = 0

    def next_turn(self, _request, observations, _calls):
        from core.llm_clients import client as llm

        for observation in observations[self.sent:]:
            if observation.tool_results:
                validate_results(self.pending, observation.tool_results)
                self.messages.extend({
                    "role": "tool", "tool_call_id": result.call_id,
                    "content": result_text(result.content),
                } for result in observation.tool_results)
                self.pending = []
            else:
                if self.pending:
                    raise AdapterProtocolError("Pending tool calls are missing their results")
                self.messages.append({"role": "user", "content": observation.summary})
            self.sent += 1
        cap = llm._get_route_capabilities(self.provider, self.model)
        streaming = (self.stream_first and self.turn == 0 and cap.supports_stream is not False) or cap.requires_stream is True
        kwargs = {**self.options, "model": self.model, "messages": snapshot(self.messages), "stream": streaming}
        for name in cap.unsupported_parameters:
            if name not in {"tools", "messages", "model", "stream"}:
                kwargs.pop(name, None)
        for _attempt in range(8):
            try:
                response = self.client.chat.completions.create(**snapshot(kwargs))
                if kwargs["stream"]:
                    message, finish = self._read_stream(response)
                else:
                    choices = value(response, "choices", []) or []
                    if not choices:
                        raise AdapterProtocolError("Provider returned no completion choice")
                    message, finish = value(choices[0], "message"), value(choices[0], "finish_reason")
                turn = self._decode(message, finish)
                self.turn += 1
                llm._update_route_capabilities(self.provider, self.model, supports_tools=True)
                return turn
            except Exception as exc:
                if isinstance(exc, AdapterProtocolError):
                    if (
                        _attempt == 0
                        and str(exc) == "Provider returned neither text nor complete tool calls"
                        and any(observation.tool_results for observation in observations)
                    ):
                        # Some compatible endpoints return an empty final turn
                        # after a successful tool result. Ask for text once,
                        # with tools removed so no operation can be repeated.
                        self.messages.append({"role": "user", "content": (
                            "The tool operation has already finished. Give a brief plain-language "
                            "answer using the existing tool results. Do not repeat any operation."
                        )})
                        kwargs["messages"] = snapshot(self.messages)
                        for name in ("tools", "parallel_tool_calls", "tool_choice"):
                            kwargs.pop(name, None)
                        continue
                    raise
                # No tools have executed during this SDK request. Retry only a
                # concrete formatting/transport rejection, never an auth error.
                if llm._tools_not_supported_error(exc):
                    raise
                if llm._requires_stream_error(exc) and not kwargs["stream"]:
                    kwargs["stream"] = True
                    llm._update_route_capabilities(self.provider, self.model, requires_stream=True)
                    continue
                if kwargs["stream"] and llm._stream_mode_error(exc):
                    kwargs["stream"] = False
                    llm._update_route_capabilities(self.provider, self.model, supports_stream=False)
                    continue
                adjusted = llm._recover_openai_compat_kwargs(self.provider, self.model, kwargs, exc)
                if adjusted is None or adjusted == kwargs or "tools" not in adjusted:
                    raise
                kwargs = adjusted
                self.options = {k: deepcopy(v) for k, v in kwargs.items() if k not in {"messages", "stream"}}
        raise AdapterProtocolError("Provider kept rejecting the request after bounded compatibility retries")

    def _read_stream(self, response):
        from core.llm_clients import client as llm

        accumulator = StreamToolCallAccumulator()
        texts, reasoning, details = [], [], []
        finish, refusal = None, ""
        context = response if hasattr(response, "__enter__") else nullcontext(response)
        try:
            with context as stream:
                for event in stream:
                    choices = value(event, "choices", []) or []
                    if not choices:
                        continue  # Usage-only events have no choice.
                    choice = choices[0]
                    # Ignore other choices rather than merging unrelated calls.
                    if value(choice, "index", 0) not in (None, 0):
                        continue
                    finish = value(choice, "finish_reason") or finish
                    delta = value(choice, "delta", {})
                    text = text_content(value(delta, "content"))
                    if text:
                        texts.append(text)
                        llm._emit_live_progress("".join(texts))
                    reasoning.append(str(value(delta, "reasoning_content") or value(delta, "reasoning", "") or ""))
                    details.extend(snapshot(value(delta, "reasoning_details", []) or []))
                    refusal += str(value(delta, "refusal", "") or "")
                    for fragment in value(delta, "tool_calls", []) or []:
                        accumulator.add(fragment)
        finally:
            if not hasattr(response, "__enter__") and callable(getattr(response, "close", None)):
                response.close()
        if finish is None:
            raise AdapterProtocolError("Provider stream ended without a completion marker")
        message = {"content": "".join(texts) or None, "tool_calls": [
            tool_call_payload(call) for call in accumulator.calls.values()
        ]}
        if any(reasoning):
            message["reasoning_content"] = "".join(reasoning)
        if details:
            message["reasoning_details"] = details
        if refusal:
            message["refusal"] = refusal
        return message, finish

    def _decode(self, message, finish):
        calls = [tool_call(
            entry["id"], entry["name"], entry["arguments"], provider_payload=entry,
        ) for entry in complete_calls(message).values()]
        check_terminal(finish, has_calls=bool(calls))
        validate_call_ids(calls)
        if value(message, "refusal"):
            raise AdapterProtocolError("Provider refused the request")
        text = text_content(value(message, "content"))
        if not calls and not text:
            raise AdapterProtocolError("Provider returned neither text nor complete tool calls")
        assistant = {"role": "assistant", "content": text or None}
        if calls:
            assistant["tool_calls"] = [tool_call_payload(call.provider_payload) for call in calls]
        for name in ("reasoning", "reasoning_content", "reasoning_details", "extra_content"):
            extra = value(message, name)
            if extra is not None:
                assistant[name] = snapshot(extra)
        self.messages.append(assistant)
        self.pending = calls
        return ChatModelTurn(tool_calls=calls, progress=text if calls else "", final_text="" if calls else text, status="continue" if calls else "final")
