"""Protocol-independent requests for required planning/rewrite functions.

These requests only extract structured arguments. They never execute the
requested application action or enable a provider's built-in tools.
"""
from __future__ import annotations

from copy import deepcopy

from core.llm_clients.adapter_protocol import AdapterCapabilityError, AdapterProtocolError, argument_error
from core.llm_clients.chat_tool_loop import ChatToolRequest
from core.llm_clients.provider_adapters import Protocol, adapter_for


def responses_kwargs(kwargs: dict) -> dict:
    """Translate an existing text-only completion request to Responses."""
    instructions, inputs = [], []
    for message in kwargs.get("messages", []):
        content = message.get("content")
        if not isinstance(content, str):
            raise AdapterCapabilityError("This text/tool adapter does not forward non-text message content")
        if message["role"] in {"system", "developer"}:
            instructions.append(content)
        else:
            inputs.append({"role": message["role"], "content": content})
    result = {
        "model": kwargs["model"], "instructions": "\n\n".join(instructions),
        "input": inputs, "store": False,
    }
    if kwargs.get("tools"):
        result["tools"] = [{"type": "function", **deepcopy(tool.get("function", tool))}
                           for tool in kwargs["tools"]]
        result["include"] = ["reasoning.encrypted_content"]
    limit = kwargs.get("max_completion_tokens", kwargs.get("max_tokens"))
    if limit is not None:
        result["max_output_tokens"] = limit
    return result


def required_tool_call(provider: str, model: str, *, system: str, prompt: str, tool: dict, max_tokens: int, stream: bool = True):
    """Ask any active transport for exactly one validated function call."""
    from core.llm_clients import client as llm
    from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
    from core.llm_clients.chat_completions_adapter import ChatCompletionsLoopModel
    from core.llm_clients.responses_chat_adapter import ResponsesChatLoopModel

    adapter = adapter_for(provider, model)
    definition = deepcopy(tool.get("function", tool))
    name = definition["name"]
    request = ChatToolRequest(
        messages=[{"role": "user", "content": prompt}], system_prompt=system,
        model_route={"provider": provider, "model": model},
        tools=[{"type": "function", "function": definition}], allowed_tools=[name],
        pinned_tools=[name], permissions={}, budgets={"max_tool_calls": 1},
    )
    if adapter.protocol == Protocol.COPILOT:
        from core.auth import copilot_client
        from core.llm_clients.chat_tool_loop import OpenWandToolResult

        recorded = []

        class Recorder:
            def execute(self, call):
                recorded.append(call)
                return OpenWandToolResult(call.id, call.name, True, "Arguments recorded for review. Do not call again.")

        copilot_client.ask(prompt, model, system=system, tool_request=request, tool_executor=Recorder(), max_tool_calls=1)
        calls = recorded
    elif adapter.protocol == Protocol.ANTHROPIC:
        # Current Claude thinking models reject forced tool_choice. Requiring
        # the returned call below preserves the contract with auto selection.
        native = {"name": name, "description": definition.get("description", ""),
                  "input_schema": definition.get("parameters", {})}
        options = {}
        if not any(part in model.lower() for part in ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "haiku-5", "fable")):
            options["tool_choice"] = {"type": "tool", "name": name}
        engine = AnthropicChatLoopModel(
            llm._dynamic_anthropic_client(), model=model, system=system,
            messages=deepcopy(request.messages), tools=[native], max_tokens=max_tokens,
            request_options=options,
        )
        calls = engine.next_turn(request, [], []).tool_calls
    else:
        kwargs = {"model": model, "messages": [{"role": "system", "content": system}, *request.messages],
                  "tools": request.tools, "stream": stream}
        llm._apply_max_output(kwargs, model, max_tokens)
        if adapter.protocol == Protocol.RESPONSES:
            options = responses_kwargs(kwargs)
            options["tool_choice"] = {"type": "function", "name": name}
            client = llm._get_codex_client() if provider == "chatgpt" else llm._dynamic_openai_client(provider)
            engine = ResponsesChatLoopModel(
                client, model=model, instructions=system, tools=options["tools"],
                initial_input=options["input"], provider=provider, request_options=options,
            )
        else:
            kwargs["tool_choice"] = {"type": "function", "function": {"name": name}}
            engine = ChatCompletionsLoopModel(
                llm._dynamic_openai_client(provider), provider=provider, model=model, kwargs=kwargs,
            )
        calls = engine.next_turn(request, [], []).tool_calls
    if len(calls) != 1 or calls[0].name != name or calls[0].validation_error:
        raise AdapterProtocolError(f"Planning model must return exactly one valid {name} call")
    if argument_error(calls[0].arguments, definition.get("parameters", {})):
        raise AdapterProtocolError(f"Planning model returned arguments outside the {name} schema")
    return calls[0]
