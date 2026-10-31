"""Anthropic adapter for the provider-neutral chat tool loop."""
from __future__ import annotations

from typing import Any

from core.llm_clients.adapter_protocol import (
    AdapterProtocolError,
    check_terminal,
    snapshot,
    tool_call,
    validate_call_ids,
    validate_results,
    value,
)
from core.llm_clients.chat_tool_loop import (
    ChatLoopModel,
    ChatModelTurn,
    ChatToolRequest,
    OpenWandObservation,
    OpenWandToolCall,
)


class AnthropicChatLoopModel(ChatLoopModel):
    """Claude Messages adapter for the provider-neutral loop."""

    def __init__(
        self,
        client,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int,
        provider: str = "anthropic",
        request_options: dict[str, Any] | None = None,
    ):
        """Initialize the Anthropic adapter."""
        self._client = client
        self._model = model
        self._system = system
        self._messages = snapshot(messages)
        self._tools = snapshot(tools)
        self._max_tokens = max_tokens
        self._provider = provider
        self._sent_observations = 0
        self._pending: list[OpenWandToolCall] = []
        self._options = snapshot(request_options or {})

    def next_turn(
        self,
        _request: ChatToolRequest,
        observations: list[OpenWandObservation],
        _tool_calls: list[OpenWandToolCall],
    ) -> ChatModelTurn:
        """Call Claude Messages and normalize the result into one model turn."""
        from core.llm_clients import client as llm

        for observation in observations[self._sent_observations:]:
            if observation.tool_results:
                validate_results(self._pending, observation.tool_results)
                self._messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.call_id,
                            "content": result.content,
                            **({"is_error": True} if not result.ok else {}),
                        }
                        for result in observation.tool_results
                    ],
                })
                self._pending = []
            else:
                if self._pending:
                    raise AdapterProtocolError("Pending Claude tool calls have no results")
                self._messages.append({
                    "role": "user",
                    "content": observation.summary,
                })
            self._sent_observations += 1

        response = self._client.messages.create(
            **self._options,
            model=self._model,
            max_tokens=self._max_tokens,
            system=self._system,
            messages=snapshot(self._messages),
            tools=snapshot(self._tools),
        )
        reason = value(response, "stop_reason")
        check_terminal(reason)
        llm._update_route_capabilities(self._provider, self._model, supports_tools=True)
        text_blocks: list[str] = []
        calls: list[OpenWandToolCall] = []
        content = value(response, "content", []) or []
        for block in content:
            if value(block, "type", "") == "text":
                text = value(block, "text", "")
                if text:
                    text_blocks.append(text)
                continue
            if value(block, "type", "") != "tool_use":
                continue
            calls.append(
                tool_call(
                    value(block, "id", ""),
                    value(block, "name", ""),
                    value(block, "input", {}),
                    provider_payload={
                        "id": value(block, "id", ""),
                        "name": value(block, "name", ""),
                        "input": snapshot(value(block, "input", {})),
                    },
                )
            )
        validate_call_ids(calls)
        if reason == "tool_use" and not calls:
            raise AdapterProtocolError("Claude reported tool use without complete tool calls")
        if not calls and not text_blocks:
            raise AdapterProtocolError("Claude returned neither text nor tool calls")
        self._messages.append({"role": "assistant", "content": snapshot(content)})
        self._pending = calls
        if calls:
            return ChatModelTurn(tool_calls=calls, progress="".join(text_blocks))
        return ChatModelTurn(final_text="".join(text_blocks), status="final")
