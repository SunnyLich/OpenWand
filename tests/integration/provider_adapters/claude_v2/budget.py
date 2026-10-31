"""Fail-closed, no-refund reservation guard for this synthetic Claude QA run.

Rates verified 2026-10-11 against official model/pricing documentation.
All amounts are integer micro-dollars: input=1, output=5 per token.
Counts are estimates; reserve max(2*count+1024, full JSON UTF-8 bytes+1024).
Only small text/custom-tool requests are supported. No caching, thinking,
images, server tools, beta parameters, model aliases, or alternate endpoints.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
from contextlib import contextmanager

MODEL = "claude-haiku-4-5-20251001"
PRICE_DATE = "2026-10-11"
CAP_MICRO_USD = 200_000
MAX_REQUESTS = 36
MAX_OUTPUT = 256
PRICING_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
COUNTING_URL = "https://platform.claude.com/docs/en/build-with-claude/token-counting"


class GuardAbort(RuntimeError):
    """Sanitized fatal error, never carrying request headers or a provider body."""

    # Never persist arbitrary exception text, even when a caller uses this class.
    _CODES = {
        "unsupported content block": "unsupported_content_block",
        "direct model tool callers only": "non_direct_tool_caller",
        "request or total reservation cap reached": "reservation_or_request_cap",
        "fixed model required": "fixed_model_required",
        "output cap rejected": "output_cap_rejected",
        "synthetic payload byte ceiling exceeded": "payload_byte_ceiling",
        "unreliable token count": "unreliable_token_count",
        "usage exceeded validated bounds; stopped": "usage_bound_violation",
        "run already aborted; retries forbidden": "already_aborted",
    }

    def __init__(self, message):
        super().__init__(message)
        self.code = self._CODES.get(message, "local_guard_rejection")


def plain(value):
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    return value


def validate_payload(kwargs):
    p = plain(copy.deepcopy(kwargs))
    if set(p) - {"model", "max_tokens", "system", "messages", "tools", "temperature"}:
        raise GuardAbort("unsupported request fields")
    if p.get("model") != MODEL:
        raise GuardAbort("fixed model required")
    if type(p.get("max_tokens")) is not int or not 1 <= p["max_tokens"] <= MAX_OUTPUT:
        raise GuardAbort("output cap rejected")
    if not isinstance(p.get("system", ""), str):
        raise GuardAbort("text system required")
    if not isinstance(p.get("messages"), list) or not p["messages"]:
        raise GuardAbort("messages required")
    for message in p["messages"]:
        if set(message) != {"role", "content"} or message["role"] not in {
            "user",
            "assistant",
        }:
            raise GuardAbort("unsupported message shape")
        content = message["content"]
        if isinstance(content, str):
            continue
        if not isinstance(content, list):
            raise GuardAbort("unsupported message content")
        for b in content:
            allowed = {
                "text": {"type", "text"},
                "tool_use": {"type", "id", "name", "input", "caller"},
                "tool_result": {"type", "tool_use_id", "content", "is_error"},
            }
            if not isinstance(b, dict) or b.get("type") not in allowed or set(b) - allowed[b["type"]]:
                raise GuardAbort("unsupported content block")
            if b["type"] == "tool_result" and not isinstance(b.get("content"), str):
                raise GuardAbort("text tool result required")
            if b["type"] == "text" and not isinstance(b.get("text"), str):
                raise GuardAbort("text block required")
            if b["type"] == "tool_use" and (
                not b.get("name", "").startswith("qa_") or not isinstance(b.get("input"), dict)
            ):
                raise GuardAbort("synthetic tool call required")
            if "caller" in b and b["caller"] != {"type": "direct"}:
                raise GuardAbort("direct model tool callers only")
    for tool in p.get("tools", []):
        if set(tool) != {"name", "description", "input_schema"} or not tool["name"].startswith("qa_"):
            raise GuardAbort("synthetic custom tools only")
    blob = json.dumps(p, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(blob) > 12_000:
        raise GuardAbort("synthetic payload byte ceiling exceeded")
    return p, len(blob)


class Budget:
    def __init__(self, *, today=None):
        if (today or dt.datetime.now(dt.UTC).date()).isoformat() != PRICE_DATE:
            raise GuardAbort("pricing verification expired; review official pricing before another run")
        self.records = []
        self.count_requests = 0
        self.poisoned = False
        self.abort_info = None
        self.generation_limit = MAX_REQUESTS

    @property
    def reserved(self):
        return sum(r["reserved_micro_usd"] for r in self.records)

    def reserve(self, count, byte_count, max_output):
        if self.poisoned:
            raise GuardAbort("run already aborted; retries forbidden")
        if type(count) is not int or not 0 <= count <= 8000:
            raise GuardAbort("unreliable token count")
        if type(byte_count) is not int or not 0 < byte_count <= 12_000:
            raise GuardAbort("unreliable byte bound")
        if type(max_output) is not int or not 1 <= max_output <= MAX_OUTPUT:
            raise GuardAbort("invalid output reservation")
        upper = max(2 * count + 1024, byte_count + 1024)
        amount = upper + 5 * max_output
        if len(self.records) >= min(MAX_REQUESTS, self.generation_limit) or self.reserved + amount > CAP_MICRO_USD:
            raise GuardAbort("request or total reservation cap reached")
        record = {
            "request": len(self.records) + 1,
            "counted_input_tokens": count,
            "input_token_bound": upper,
            "max_output_tokens": max_output,
            "reserved_micro_usd": amount,
            "status": "reserved",
            "mode": "create",
        }
        self.records.append(record)
        return record

    def complete(self, record, message):
        u = message.usage
        inp, out = u.input_tokens, u.output_tokens
        cache = (getattr(u, "cache_creation_input_tokens", 0) or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
        record.update(
            input_tokens=inp,
            output_tokens=out,
            estimated_micro_usd=inp + 5 * out,
            stop_reason=getattr(message, "stop_reason", None),
            status="complete",
        )
        record["provider_text"] = "".join(
            getattr(b, "text", "") for b in getattr(message, "content", []) if getattr(b, "type", "") == "text"
        )
        record["provider_tool_calls"] = [
            {"name": b.name, "arguments": plain(b.input)}
            for b in getattr(message, "content", [])
            if getattr(b, "type", "") == "tool_use"
        ]
        if (
            type(inp) is not int
            or type(out) is not int
            or inp < 0
            or out < 0
            or cache
            or inp > record["input_token_bound"]
            or out > record["max_output_tokens"]
        ):
            self.poisoned = True
            raise GuardAbort("usage exceeded validated bounds; stopped")

    def summary(self):
        return {
            "generation_requests": len(self.records),
            "count_tokens_requests": self.count_requests,
            "reserved_usd": self.reserved / 1_000_000,
            "input_tokens": sum(r.get("input_tokens", 0) for r in self.records),
            "output_tokens": sum(r.get("output_tokens", 0) for r in self.records),
            "estimated_cost_usd": sum(r.get("estimated_micro_usd", 0) for r in self.records) / 1_000_000,
            "usage_complete": all(r["status"] == "complete" for r in self.records),
            "abort": self.abort_info,
            "records": self.records,
        }

    def restore_completed_prefix(self, summary):
        """Keep all prior reservations; permit only previously unstarted cases.

        A remote failure or uncertain usage makes continuation impossible.
        This is for a local validation failure before count/generation I/O.
        """
        if summary.get("abort") != {"error_class": "GuardAbort", "http_status": None}:
            raise GuardAbort("only the recorded local compatibility rejection can continue")
        self._restore_records(summary)

    def restore_successful_ledger(self, summary):
        """Restore fully accounted usage for an explicitly authorized targeted case."""
        if summary.get("abort") is not None or summary.get("usage_complete") is not True:
            raise GuardAbort("prior provider usage must be complete")
        self._restore_records(summary)
        restored = self.summary()
        for field in ("reserved_usd", "estimated_cost_usd", "input_tokens", "output_tokens"):
            if restored[field] != summary[field]:
                self.poisoned = True
                raise GuardAbort("prior usage totals do not match ledger")

    def _restore_records(self, summary):
        if self.records or self.count_requests:
            raise GuardAbort("cannot reset a running budget")
        records = copy.deepcopy(summary["records"])
        if summary["count_tokens_requests"] != len(records) or summary["generation_requests"] != len(records):
            raise GuardAbort("uncertain prior I/O; no continuation")
        if not records or len(records) > MAX_REQUESTS:
            raise GuardAbort("invalid prior ledger")
        for i, r in enumerate(records, 1):
            if r["request"] != i or r["status"] != "complete":
                raise GuardAbort("incomplete prior generation; no continuation")
            if r["reserved_micro_usd"] != r["input_token_bound"] + 5 * r["max_output_tokens"]:
                raise GuardAbort("invalid prior reservation")
            if (
                not 0 <= r["input_tokens"] <= r["input_token_bound"]
                or not 0 <= r["output_tokens"] <= r["max_output_tokens"] <= MAX_OUTPUT
            ):
                raise GuardAbort("invalid prior usage")
            if r["input_token_bound"] < 2 * r["counted_input_tokens"] + 1024:
                raise GuardAbort("prior reservation lacks headroom")
        if sum(r["reserved_micro_usd"] for r in records) > CAP_MICRO_USD:
            raise GuardAbort("prior cap exhausted")
        self.records = records
        self.count_requests = summary["count_tokens_requests"]


class GuardedMessages:
    """Wrap SDK Messages, guarding every actual adapter request and tool round."""

    def __init__(self, messages, budget):
        self._messages, self.budget = messages, budget
        self._stage = "not_started"

    def _prepare(self, kwargs):
        self._stage = "payload_validation"
        if self.budget.poisoned:
            raise GuardAbort("run already aborted; retries forbidden")
        p, size = validate_payload(kwargs)
        counted = {k: v for k, v in p.items() if k in {"model", "system", "messages", "tools"}}
        self._stage = "token_count_preflight"
        self.budget.count_requests += 1
        count = self._messages.count_tokens(**counted).input_tokens
        self._stage = "reservation"
        record = self.budget.reserve(count, size, p["max_tokens"])
        p["service_tier"] = "standard_only"
        return p, record

    def _abort(self, exc, record=None):
        self.budget.poisoned = True
        if self.budget.abort_info is None:
            self.budget.abort_info = {
                "error_class": type(exc).__name__,
                "http_status": getattr(exc, "status_code", None),
                "stage": self._stage,
                "guard_code": exc.code if isinstance(exc, GuardAbort) else None,
            }
        if record is not None:
            record.update(
                status="error",
                error_class=type(exc).__name__,
                http_status=getattr(exc, "status_code", None),
            )
        raise GuardAbort("provider or guard failure: " + type(exc).__name__) from None

    def create(self, **kwargs):
        record = None
        try:
            p, record = self._prepare(kwargs)
            self._stage = "generation"
            response = self._messages.create(**p)
            self._stage = "usage_verification"
            self.budget.complete(record, response)
            return response
        except Exception as exc:
            self._abort(exc, record)

    @contextmanager
    def stream(self, **kwargs):
        record = None
        try:
            p, record = self._prepare(kwargs)
            record["mode"] = "stream"
            self._stage = "generation_stream"
            with self._messages.stream(**p) as stream:
                yield stream
                self._stage = "usage_verification"
                self.budget.complete(record, stream.get_final_message())
        except Exception as exc:
            self._abort(exc, record)
