"""Offline review of guard compatibility and separation of grading concerns."""

import copy
from datetime import date
from types import SimpleNamespace as NS

import pytest
from anthropic.types import Message, ToolUseBlock

from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
from core.llm_clients.chat_tool_loop import ChatToolLoop, ChatToolLoopConfig

from . import budget as budget_module
from .budget import MODEL, Budget, GuardAbort, GuardedMessages, plain, validate_payload
from .scenarios import SCENARIOS, SYSTEM, expected_calls, grade, grade_dimensions, schemas
from .test_adapters import Executor, request
from .test_budget import FakeMessages, payload


def legacy_allowlist_repro(kwargs):
    """Reconstruct only the original rejecting predicate; not a recovered payload."""
    p, size = validate_payload(kwargs)
    for message in p["messages"]:
        if not isinstance(message["content"], list):
            continue
        for block in message["content"]:
            if block["type"] == "tool_use" and set(block) - {"type", "id", "name", "input"}:
                raise GuardAbort("unsupported content block")
    return p, size


class SDKRoundTrip:
    def __init__(self):
        self.counted = []
        self.created = []

    def count_tokens(self, **kwargs):
        self.counted.append(copy.deepcopy(kwargs))
        return NS(input_tokens=100)

    def create(self, **kwargs):
        self.created.append(copy.deepcopy(kwargs))
        content = (
            [
                ToolUseBlock(
                    type="tool_use", id="tool_qa", name="qa_add", input={"a": 2, "b": 3}, caller={"type": "direct"}
                )
            ]
            if len(self.created) == 1
            else [{"type": "text", "text": "5"}]
        )
        return Message(
            id="msg_qa",
            type="message",
            role="assistant",
            model=MODEL,
            content=content,
            stop_reason="tool_use" if len(self.created) == 1 else "end_turn",
            usage={"input_tokens": 100, "output_tokens": 20},
        )


def make_roundtrip():
    scenario = SCENARIOS[1]
    wire, ledger = SDKRoundTrip(), Budget(today=date(2026, 10, 11))
    req = request(scenario, "anthropic")
    adapter = AnthropicChatLoopModel(
        NS(messages=GuardedMessages(wire, ledger)),
        model=MODEL,
        system=SYSTEM,
        messages=req.messages,
        tools=schemas(scenario, "anthropic"),
        max_tokens=256,
    )
    return wire, ledger, req, adapter


def test_legacy_sdk_rejection_is_payload_validation_not_budget_cap(monkeypatch):
    wire, b, req, adapter = make_roundtrip()
    monkeypatch.setattr(budget_module, "validate_payload", legacy_allowlist_repro)
    with pytest.raises(GuardAbort):
        ChatToolLoop(ChatToolLoopConfig(max_rounds=3, max_tool_calls=2)).run(req, adapter, Executor())
    assert b.abort_info["stage"] == "payload_validation"
    assert b.abort_info["guard_code"] == "unsupported_content_block"
    assert len(wire.counted) == len(wire.created) == len(b.records) == 1
    assert b.reserved < 200_000


def test_fixed_guard_roundtrips_sdk_caller_through_actual_adapter():
    wire, b, req, adapter = make_roundtrip()
    executor = Executor()
    result = ChatToolLoop(ChatToolLoopConfig(max_rounds=3, max_tool_calls=2)).run(req, adapter, executor)
    assert result.text == "5"
    assert executor.calls == [("qa_add", {"a": 2, "b": 3})]
    assert len(wire.counted) == len(wire.created) == len(b.records) == 2
    assert wire.counted[1]["messages"] == wire.created[1]["messages"]
    assert wire.counted[1]["messages"][-2]["content"][0]["caller"] == {"type": "direct"}
    assert wire.counted[1]["messages"][-1]["content"][0]["tool_use_id"] == "tool_qa"
    assert b.summary()["usage_complete"]


def test_safe_diagnostics_distinguish_true_cap_from_payload_rejection():
    b = Budget(today=date(2026, 10, 11))
    for _ in range(36):
        b.reserve(1, 1, 1)
    m = FakeMessages()
    with pytest.raises(GuardAbort):
        GuardedMessages(m, b).create(**payload())
    assert b.abort_info["stage"] == "reservation"
    assert b.abort_info["guard_code"] == "reservation_or_request_cap"
    assert len(m.counted) == 1 and not m.created


def test_safe_diagnostics_never_persist_provider_error_text():
    b, m = Budget(today=date(2026, 10, 11)), FakeMessages("count")
    g = GuardedMessages(m, b)
    for _ in range(2):
        with pytest.raises(GuardAbort):
            g.create(**payload())
    assert b.abort_info == {
        "error_class": "RuntimeError",
        "http_status": None,
        "stage": "token_count_preflight",
        "guard_code": None,
    }
    assert "sentinel" not in str(b.summary())


@pytest.mark.parametrize("text", ["RECORDED", "RECORDED.", "  RECORDED!\n"])
def test_json_acknowledgment_accepts_incidental_punctuation(text):
    s = SCENARIOS[3]
    dims = grade_dimensions(s, expected_calls(s), text)
    assert dims["tool_contract"] == dims["answer_content"] == "passed"
    assert (dims["exact_output"] == "passed") == (text.strip() == "RECORDED")


@pytest.mark.parametrize("text", ["NOT RECORDED", "RECORDED twice", "recorded", "", "RECORDED RECORDED"])
def test_semantic_grader_does_not_hide_wrong_content(text):
    s = SCENARIOS[3]
    assert grade_dimensions(s, expected_calls(s), text)["answer_content"] == "failed"


@pytest.mark.parametrize("text", ["9 IRIS", "9, IRIS.", "9\nIRIS"])
def test_multi_tool_answer_retains_both_values(text):
    s = SCENARIOS[5]
    dims = grade_dimensions(s, expected_calls(s), text, list(s.rounds))
    assert dims["tool_contract"] == dims["answer_content"] == "passed"


@pytest.mark.parametrize("text", ["IRIS " * 9, "8 IRIS", "9 IRIS IRIS", "IRIS", "9 iris", "9 or 10 IRIS"])
def test_multi_tool_wrong_answer_not_reclassified_as_semantic_pass(text):
    s = SCENARIOS[5]
    dims = grade_dimensions(s, expected_calls(s), text, list(s.rounds))
    assert dims["tool_contract"] == "passed" and dims["answer_content"] == "failed"


def test_semantic_grader_still_checks_json_types_and_all_tools():
    s = SCENARIOS[3]
    wrong = copy.deepcopy(expected_calls(s))
    wrong[0][1]["payload"]["items"][1] = 1
    assert grade_dimensions(s, wrong, "RECORDED.")["tool_contract"] == "failed"
    s = SCENARIOS[5]
    assert grade_dimensions(s, expected_calls(s)[:1], "9 IRIS")["tool_contract"] == "failed"
    assert grade_dimensions(s, expected_calls(s), "9 IRIS", [[1], [2]])["tool_contract"] == "failed"


def test_original_strict_results_remain_available():
    s = SCENARIOS[3]
    assert grade(s, expected_calls(s), "RECORDED.") == ["final_text"]
    assert plain(ToolUseBlock(type="tool_use", id="x", name="qa_add", input={}, caller={"type": "direct"}))[
        "caller"
    ] == {"type": "direct"}
