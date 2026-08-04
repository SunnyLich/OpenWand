"""Tests for Ctrl+Shift+Q rewrite tool-call extraction."""

from types import SimpleNamespace

from core.llm_clients import client as llm


def test_openai_compat_rewrite_forces_tool_call_and_extracts_replacement(monkeypatch):
    """Verify OpenAI-compatible rewrite pastes only rewrite_selection text."""
    calls: list[dict] = []

    tool_call = SimpleNamespace(
        id="call_1",
        function=SimpleNamespace(
            name="rewrite_selection",
            arguments=(
                '{"replacement_text": "Text 2 body", '
                '"assistant_response": "I used the source text for the replacement."}'
            ),
        ),
    )
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Text 2 body", tool_calls=[tool_call])
            )
        ]
    )

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return response

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=Completions())
    )
    monkeypatch.setattr(llm, "_dynamic_openai_client", lambda _provider: fake_client)
    monkeypatch.setattr(llm, "_use_macos_openai_compat_non_streaming", lambda _provider: True)

    chunks = list(llm._stream_openai_compat_rewrite_tool("openai", "gpt-test", "prompt"))

    assert calls
    assert calls[0]["tools"][0]["function"]["name"] == "rewrite_selection"
    assert calls[0]["tool_choice"]["function"]["name"] == "rewrite_selection"
    assert "assistant_response" in calls[0]["tools"][0]["function"]["parameters"]["required"]
    assert [(getattr(chunk, "kind", ""), str(chunk)) for chunk in chunks] == [
        ("progress", "I used the source text for the replacement."),
        ("rewrite_result", "Text 2 body"),
    ]


def test_responses_rewrite_forces_tool_call_and_extracts_replacement(monkeypatch):
    """Verify Responses rewrite asks for rewrite_selection and extracts it."""
    calls: list[dict] = []

    def fake_create(_client, kwargs, *, model):
        calls.append(kwargs)
        return {
            "output_text": "Ready.",
            "output": [
                {
                    "type": "function_call",
                    "name": "rewrite_selection",
                    "call_id": "call_1",
                    "arguments": (
                        '{"replacement_text": "Text 2 body", '
                        '"assistant_response": "I used the source text for the replacement."}'
                    ),
                }
            ],
        }

    monkeypatch.setattr(llm, "_get_codex_client", lambda: object())
    monkeypatch.setattr(llm, "_responses_rewrite_create_with_retries", fake_create)

    chunks = list(llm._stream_responses_rewrite_tool("gpt-test", "prompt"))

    assert calls
    assert calls[0]["tools"][0]["name"] == "rewrite_selection"
    assert calls[0]["tool_choice"]["name"] == "rewrite_selection"
    assert "assistant_response" in calls[0]["tools"][0]["parameters"]["required"]
    assert [(getattr(chunk, "kind", ""), str(chunk)) for chunk in chunks] == [
        ("progress", "I used the source text for the replacement."),
        ("rewrite_result", "Text 2 body"),
    ]


def test_responses_rewrite_streams_safe_reasoning_before_tool_result(monkeypatch):
    """Rewrite uses low-effort streaming and surfaces only provider summaries."""
    calls: list[dict] = []
    arguments = (
        '{"replacement_text": "Welcome, Sam!", '
        '"assistant_response": "I made the greeting warmer."}'
    )
    events = [
        SimpleNamespace(type="response.reasoning_summary_text.delta", delta="Updating the greeting. "),
        SimpleNamespace(
            type="response.output_item.added",
            output_index=0,
            item=SimpleNamespace(
                id="item_1",
                type="function_call",
                call_id="call_1",
                name="rewrite_selection",
                arguments="",
            ),
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            output_index=0,
            item_id="item_1",
            call_id="call_1",
            name="rewrite_selection",
            delta=arguments,
            arguments="",
        ),
        SimpleNamespace(
            type="response.function_call_arguments.done",
            output_index=0,
            item_id="item_1",
            call_id="call_1",
            name="rewrite_selection",
            delta="",
            arguments=arguments,
        ),
    ]

    class FakeStream:
        def __enter__(self):
            return iter(events)

        def __exit__(self, exc_type, exc, tb):
            return False

    class Responses:
        def stream(self, **kwargs):
            calls.append(kwargs)
            return FakeStream()

    fake_client = SimpleNamespace(responses=Responses())
    monkeypatch.setattr(llm, "_get_codex_client", lambda: fake_client)

    chunks = list(llm._stream_responses_rewrite_tool("gpt-test", "prompt"))

    assert calls[0]["reasoning"] == {"effort": "none"}
    assert calls[0]["extra_body"]["stream"] is True
    assert [(getattr(chunk, "kind", ""), str(chunk)) for chunk in chunks] == [
        ("thought", "Updating the greeting. "),
        ("progress", "I made the greeting warmer."),
        ("rewrite_result", "Welcome, Sam!"),
    ]
