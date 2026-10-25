import copy
from datetime import date
from types import SimpleNamespace as NS

import pytest

from .budget import (
    CAP_MICRO_USD,
    MODEL,
    Budget,
    GuardAbort,
    GuardedMessages,
    validate_payload,
)


def payload():
    return dict(
        model=MODEL,
        max_tokens=256,
        system="synthetic",
        messages=[{"role": "user", "content": "hello"}],
    )


def budget():
    return Budget(today=date(2026, 10, 11))


def response(inp=100, out=20):
    return NS(usage=NS(input_tokens=inp, output_tokens=out), stop_reason="end_turn")


@pytest.mark.parametrize("count", [-1, True, 0.5, None, "10", 8001])
def test_unreliable_counts_fail_closed(count):
    b = budget()
    with pytest.raises(GuardAbort):
        b.reserve(count, 100, 256)
    assert not b.records


@pytest.mark.parametrize("tokens", [0, -1, True, 257, None, "256"])
def test_output_cap(tokens):
    p = payload()
    p["max_tokens"] = tokens
    with pytest.raises(GuardAbort):
        validate_payload(p)


@pytest.mark.parametrize(
    "field,value",
    [
        ("model", "claude-haiku-4-5"),
        ("thinking", {"type": "enabled"}),
        ("service_tier", "auto"),
        ("extra_headers", {}),
        ("betas", []),
        ("cache_control", {}),
        ("system", [{"type": "text", "text": "cached"}]),
    ],
)
def test_unsupported_payload_rejected(field, value):
    p = payload()
    p[field] = value
    with pytest.raises(GuardAbort):
        validate_payload(p)


@pytest.mark.parametrize(
    "block",
    [
        {"type": "image", "source": {}},
        {"type": "tool_result", "content": [{"type": "image"}]},
        {"type": "text", "text": "x", "cache_control": {}},
        {"type": "tool_use", "name": "real_shell", "input": {}},
    ],
)
def test_modalities_and_real_tools_rejected(block):
    p = payload()
    p["messages"][0]["content"] = [block]
    with pytest.raises(GuardAbort):
        validate_payload(p)


def test_request_limit_and_no_refund():
    b = budget()
    for _ in range(36):
        r = b.reserve(1, 1, 1)
        b.complete(r, response(1, 1))
    reserved = b.reserved
    with pytest.raises(GuardAbort):
        b.reserve(1, 1, 1)
    assert len(b.records) == 36 and b.reserved == reserved
    assert b.reserved > b.summary()["estimated_cost_usd"] * 1_000_000


def test_total_cap_never_exceeded():
    b = budget()
    with pytest.raises(GuardAbort):
        for _ in range(36):
            b.reserve(8000, 12000, 256)
    assert b.reserved <= CAP_MICRO_USD
    assert len(b.records) < 36


def test_bounds_include_utf8_bytes_and_token_headroom():
    b = budget()
    p = payload()
    p["messages"][0]["content"] = "\u00e9" * 300
    _, size = validate_payload(p)
    r = b.reserve(100, size, 256)
    assert r["input_token_bound"] == max(1224, size + 1024)


def test_expired_pricing_fails_closed():
    with pytest.raises(GuardAbort):
        Budget(today=date(2026, 10, 12))


@pytest.mark.parametrize("inp,out", [(999999, 2), (100, 257), (-1, 2)])
def test_unexpected_usage_poisoned(inp, out):
    b = budget()
    r = b.reserve(100, 100, 256)
    with pytest.raises(GuardAbort):
        b.complete(r, response(inp, out))
    with pytest.raises(GuardAbort):
        b.reserve(1, 1, 1)


class FakeMessages:
    def __init__(self, fail=None):
        self.counted, self.created, self.fail = [], [], fail

    def count_tokens(self, **kwargs):
        self.counted.append(copy.deepcopy(kwargs))
        if self.fail == "count":
            raise RuntimeError("sensitive test sentinel")
        return NS(input_tokens=100)

    def create(self, **kwargs):
        self.created.append(copy.deepcopy(kwargs))
        if self.fail == "create":
            raise RuntimeError("sensitive test sentinel")
        return response()


@pytest.mark.parametrize("failure", ["count", "create"])
def test_errors_no_retry_no_secret_no_refund(failure):
    m, b = FakeMessages(failure), budget()
    g = GuardedMessages(m, b)
    for _ in range(2):
        with pytest.raises(GuardAbort) as caught:
            g.create(**payload())
        assert "sentinel" not in str(caught.value)
    assert len(m.counted) == 1
    assert len(m.created) == (failure == "create")
    assert bool(b.reserved) == (failure == "create")


def test_preflight_counts_full_system_tools_and_round_history():
    from .scenarios import SCENARIOS, schemas

    p = payload()
    p["tools"] = schemas(SCENARIOS[1], "anthropic")
    p["messages"] += [
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "c1",
                    "name": "qa_add",
                    "input": {"a": 2, "b": 3},
                }
            ],
        },
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "5"}],
        },
    ]
    m, b = FakeMessages(), budget()
    GuardedMessages(m, b).create(**p)
    assert m.counted[0] == {k: v for k, v in p.items() if k != "max_tokens"}
    assert m.created[0]["service_tier"] == "standard_only"
    assert m.created[0]["messages"] == p["messages"]


def test_overlarge_payload_rejected_before_counting():
    p = payload()
    p["messages"][0]["content"] = "x" * 12001
    m = FakeMessages()
    with pytest.raises(GuardAbort):
        GuardedMessages(m, budget()).create(**p)
    assert not m.counted and not m.created


@pytest.mark.parametrize("fail", [False, True])
def test_stream_reserves_before_io_and_records_usage(fail):
    from contextlib import contextmanager

    m, b = FakeMessages(), budget()

    @contextmanager
    def streaming(**kwargs):
        assert b.reserved > 0 and len(b.records) == 1
        assert kwargs["max_tokens"] == 256
        m.created.append(kwargs)
        if fail:
            raise RuntimeError("sensitive test sentinel")
        yield NS(text_stream=iter(["QA_OK"]), get_final_message=lambda: response())

    m.stream = streaming
    g = GuardedMessages(m, b)
    if fail:
        with pytest.raises(GuardAbort):
            with g.stream(**payload()):
                pass
        assert not b.summary()["usage_complete"]
        assert b.poisoned and b.reserved > 0
    else:
        with g.stream(**payload()) as s:
            assert list(s.text_stream) == ["QA_OK"]
        assert b.summary()["input_tokens"] == 100 and b.records[0]["mode"] == "stream"
    assert len(m.counted) == len(m.created) == 1


def test_unexpected_cache_usage_stops_run():
    b = budget()
    r = b.reserve(100, 100, 256)
    m = response()
    m.usage.cache_creation_input_tokens = 10
    with pytest.raises(GuardAbort):
        b.complete(r, m)
    assert b.poisoned


def test_sdk_direct_caller_metadata_survives_complete_preflight():
    from anthropic.types import ToolUseBlock

    p = payload()
    block = ToolUseBlock(
        id="tool_qa",
        name="qa_add",
        input={"a": 2, "b": 3},
        type="tool_use",
        caller={"type": "direct"},
    )
    p["messages"].append({"role": "assistant", "content": [block]})
    m = FakeMessages()
    GuardedMessages(m, budget()).create(**p)
    assert m.counted[0]["messages"][-1]["content"][0]["caller"] == {"type": "direct"}
    assert m.created[0]["messages"] == m.counted[0]["messages"]


def test_server_caller_metadata_rejected():
    p = payload()
    p["messages"].append(
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "c",
                    "name": "qa_add",
                    "input": {},
                    "caller": {"type": "code_execution_20250825", "tool_id": "server"},
                }
            ],
        }
    )
    with pytest.raises(GuardAbort):
        validate_payload(p)


def prior_summary():
    b = budget()
    for _ in range(3):
        r = b.reserve(100, 100, 256)
        b.complete(r, response())
    b.count_requests = 3
    b.abort_info = {"error_class": "GuardAbort", "http_status": None}
    return b.summary()


def test_continuation_retains_all_spend_and_request_count():
    previous = prior_summary()
    b = budget()
    b.restore_completed_prefix(previous)
    assert b.reserved == 3 * (1224 + 1280)
    assert b.count_requests == 3
    assert b.reserve(100, 100, 256)["request"] == 4
    assert b.reserved == 4 * (1224 + 1280)


@pytest.mark.parametrize("mutation", ["http", "uncertain_io", "incomplete", "reservation", "bound"])
def test_unsafe_continuation_rejected(mutation):
    p = prior_summary()
    if mutation == "http":
        p["abort"] = {"error_class": "APIError", "http_status": 500}
    elif mutation == "uncertain_io":
        p["count_tokens_requests"] += 1
    elif mutation == "incomplete":
        p["records"][0]["status"] = "error"
    elif mutation == "reservation":
        p["records"][0]["reserved_micro_usd"] = 1
    else:
        p["records"][0]["input_tokens"] = 999999
    with pytest.raises(GuardAbort):
        budget().restore_completed_prefix(p)


def test_continuation_never_repeats_passed_failed_or_blocked_cases():
    from .run_live import unstarted_plans
    from .scenarios import SCENARIOS

    plans = [(s, "tool_loop") for s in SCENARIOS[:4]]
    prior = {
        "cases": [
            {"scenario": s.name, "mode": mode, "status": status}
            for (s, mode), status in zip(plans, ["passed", "failed", "blocked", "skipped"], strict=True)
        ]
    }
    assert unstarted_plans(prior, plans) == plans[-1:]
