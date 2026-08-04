"""Provider and brain contracts for forced, non-executable app-action planning."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from core.llm_clients import client as llm

TOOL_NAME = "browser_plan_fill_form"
TOOL_DESCRIPTION = "Plan reviewed values for safe visible browser form fields."
ACTION_SCHEMA = {
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
        },
    },
    "required": ["assignments"],
    "additionalProperties": False,
}
TOOL_ARGUMENTS = json.dumps(
    {
        "assignments": [{"field_id": "name", "value": "Sunny"}],
        "assistant_response": "I prepared one form-field change for review.",
    }
)


def _chunk_values(chunks):
    return [(getattr(chunk, "kind", ""), str(chunk)) for chunk in chunks]


def _assert_plan_chunks(chunks):
    values = _chunk_values(chunks)
    assert values[0] == ("progress", "I prepared one form-field change for review.")
    assert values[1][0] == "action_plan_result"
    assert json.loads(values[1][1]) == {
        "tool_name": TOOL_NAME,
        "arguments": {"assignments": [{"field_id": "name", "value": "Sunny"}]},
    }


def test_openai_compat_action_plan_forces_exact_function(monkeypatch):
    calls: list[dict] = []
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content="",
            tool_calls=[SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name=TOOL_NAME, arguments=TOOL_ARGUMENTS),
            )],
        ))]
    )

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setattr(llm, "_dynamic_openai_client", lambda _provider: fake_client)

    chunks = list(llm._stream_openai_compat_action_plan(
        "openai", "gpt-test", TOOL_NAME, TOOL_DESCRIPTION,
        ACTION_SCHEMA, llm._validated_action_planning_spec(TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA)[3], "prompt",
    ))

    function = calls[0]["tools"][0]["function"]
    assert function["name"] == TOOL_NAME
    assert function["description"] == TOOL_DESCRIPTION
    assert function["strict"] is True
    assert function["parameters"]["additionalProperties"] is False
    assert function["parameters"]["required"][-1] == "assistant_response"
    assert calls[0]["tool_choice"] == {"type": "function", "function": {"name": TOOL_NAME}}
    _assert_plan_chunks(chunks)


def test_anthropic_action_plan_forces_exact_tool(monkeypatch):
    calls: list[dict] = []
    response = SimpleNamespace(content=[SimpleNamespace(
        type="tool_use",
        name=TOOL_NAME,
        input=json.loads(TOOL_ARGUMENTS),
    )])

    class Messages:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    monkeypatch.setattr(llm, "_dynamic_anthropic_client", lambda: SimpleNamespace(messages=Messages()))
    tool_schema = llm._validated_action_planning_spec(TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA)[3]

    chunks = list(llm._stream_anthropic_action_plan(
        "claude-test", TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA, tool_schema, "prompt"
    ))

    assert calls[0]["tools"] == [{
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "input_schema": tool_schema,
    }]
    assert calls[0]["tool_choice"] == {"type": "tool", "name": TOOL_NAME}
    _assert_plan_chunks(chunks)


def test_chatgpt_responses_action_plan_forces_exact_function(monkeypatch):
    calls: list[dict] = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return {
                "output": [{
                    "type": "function_call",
                    "name": TOOL_NAME,
                    "call_id": "call_1",
                    "arguments": TOOL_ARGUMENTS,
                }]
            }

    monkeypatch.setattr(llm, "_get_codex_client", lambda: SimpleNamespace(responses=Responses()))
    tool_schema = llm._validated_action_planning_spec(TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA)[3]

    chunks = list(llm._stream_responses_action_plan(
        "gpt-test", TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA, tool_schema, "prompt"
    ))

    assert calls[0]["tools"] == [{
        "type": "function",
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "parameters": tool_schema,
        "strict": True,
    }]
    assert calls[0]["tool_choice"] == {"type": "function", "name": TOOL_NAME}
    _assert_plan_chunks(chunks)


@pytest.mark.parametrize("bad_name", ["", "browser.fill", "9browser", "x" * 65])
def test_action_planning_rejects_unsafe_tool_names(bad_name):
    with pytest.raises(ValueError, match="planning_tool_name"):
        llm._validated_action_planning_spec(bad_name, TOOL_DESCRIPTION, ACTION_SCHEMA)


def test_action_planning_rejects_non_strict_schema():
    schema = {"type": "object", "properties": {"value": {"type": "string"}}, "required": []}
    with pytest.raises(ValueError, match="additionalProperties"):
        llm._validated_action_planning_spec(TOOL_NAME, TOOL_DESCRIPTION, schema)


def test_action_planning_rejects_malformed_arguments():
    with pytest.raises(ValueError, match="malformed JSON"):
        list(llm._action_plan_chunks(TOOL_NAME, ACTION_SCHEMA, "{not-json"))


def test_action_planning_rejects_missing_forced_call(monkeypatch):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="I would fill it.", tool_calls=[]))]
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: response))
    )
    monkeypatch.setattr(llm, "_dynamic_openai_client", lambda _provider: fake_client)
    tool_schema = llm._validated_action_planning_spec(TOOL_NAME, TOOL_DESCRIPTION, ACTION_SCHEMA)[3]
    with pytest.raises(ValueError, match="did not call required tool"):
        list(llm._stream_openai_compat_action_plan(
            "openai", "gpt-test", TOOL_NAME, TOOL_DESCRIPTION,
            ACTION_SCHEMA, tool_schema, "prompt",
        ))


def test_brain_action_plan_returns_arguments_and_visible_summary_without_execution(monkeypatch):
    from runtime.brain.wisp_brain import handlers

    events: list[tuple[str, object]] = []
    ctx = handlers.StreamContext(lambda event, data, _req_id: events.append((event, data)), "req-1")
    monkeypatch.setattr("config.TRUST_PRIVACY_MODE", False)

    def fake_stream(*_args, **_kwargs):
        yield llm._progress_chunk("I prepared one form-field change for review.")
        yield llm._action_plan_result_chunk({
            "tool_name": TOOL_NAME,
            "arguments": {"assignments": [{"field_id": "name", "value": "Sunny"}]},
        })

    monkeypatch.setattr(handlers, "_stream_action_plan_reply", fake_stream)
    result = handlers.brain_action_plan(
        ctx,
        planning_tool_name=TOOL_NAME,
        planning_tool_description=TOOL_DESCRIPTION,
        input_schema=ACTION_SCHEMA,
        user_prompt="Fill my name.",
        app_context={"fields": [{"id": "name", "value": ""}]},
    )

    assert result == {
        "tool_name": TOOL_NAME,
        "arguments": {"assignments": [{"field_id": "name", "value": "Sunny"}]},
        "visible_text": "I prepared one form-field change for review.",
    }
    assert [data for event, data in events if event == "reply.done"] == [result]
    assert [data for event, data in events if event == "reply.chunk"] == [{
        "text": "I prepared one form-field change for review.",
        "is_thought": False,
        "is_progress": True,
    }]


def test_brain_action_plan_rejects_missing_internal_forced_result(monkeypatch):
    from runtime.brain.wisp_brain import handlers

    ctx = handlers.StreamContext(lambda *_args: None, "req-2")
    monkeypatch.setattr("config.TRUST_PRIVACY_MODE", False)
    monkeypatch.setattr(
        handlers,
        "_stream_action_plan_reply",
        lambda *_args, **_kwargs: iter([llm._progress_chunk("Still only prose.")]),
    )
    with pytest.raises(ValueError, match="did not return required tool"):
        handlers.brain_action_plan(
            ctx,
            planning_tool_name=TOOL_NAME,
            planning_tool_description=TOOL_DESCRIPTION,
            input_schema=ACTION_SCHEMA,
            user_prompt="Fill my name.",
            app_context={},
        )
