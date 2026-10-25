"""Synthetic, side-effect-free conformance harness for production LLM adapters.

Nothing here creates an SDK client or reads provider credentials. The caller
supplies the client (a fake for offline tests, an explicitly opted-in SDK live).
"""
from __future__ import annotations

import copy
import json
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

SYSTEM = (
    "You are testing a tool adapter with synthetic fixtures. Follow the user's instructions exactly. "
    "Use tools only when their data is needed. Never invent tool results or receipt codes. "
    "After receiving results, give a short final answer including the requested receipt codes."
)
UNICODE_TEXT = 'café 雪 "quoted"\nsecond line'


def object_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or list(properties), "additionalProperties": False}


SCHEMAS = {
    "ow_weather": object_schema({"city": {"type": "string"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}}),
    "ow_sum": object_schema({"numbers": {"type": "array", "items": {"type": "number"}}}),
    "ow_catalog": object_schema({
        "filter": object_schema({"category": {"type": "string"}, "in_stock": {"type": "boolean"}}),
        "ids": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer"},
    }),
    "ow_echo": object_schema({"text": {"type": "string"}}),
    "ow_lookup": object_schema({"name": {"type": "string"}}),
    "ow_record": object_schema({"id": {"type": "string"}}),
}
DESCRIPTIONS = {
    "ow_weather": "Read the synthetic weather station for a city and unit; returns temperature and a receipt code.",
    "ow_sum": "Sum an array of numbers using the synthetic calculator; returns sum and a receipt code.",
    "ow_catalog": "Filter a synthetic catalogue by nested filter, ordered IDs, and integer limit; returns a receipt code.",
    "ow_echo": "Echo text exactly, preserving Unicode, quotes and newlines; returns a receipt code.",
    "ow_lookup": "Find a synthetic person's opaque record ID by name. Use ow_record to read the record.",
    "ow_record": "Read a synthetic record by opaque ID. An outdated ID returns an error with the replacement ID.",
}


@dataclass(frozen=True)
class Scenario:
    id: str
    prompt: str
    expected_calls: tuple[tuple[str, dict], ...] = ()
    answer_contains: tuple[str, ...] = ()
    tools_enabled: bool = True
    ordered: bool = True
    answer_exact: str | None = None


SCENARIOS = (
    Scenario("no_tools", "What is 17 + 25? Reply with only 42.", answer_contains=("42",), tools_enabled=False, answer_exact="42"),
    Scenario("no_tool_needed", "Reply with only adapter-ready. This needs no tools.", answer_contains=("adapter-ready",), answer_exact="adapter-ready"),
    Scenario("weather", "Use the weather tool for Reykjavik in celsius. Report its temperature and receipt code.",
             (("ow_weather", {"city": "Reykjavik", "unit": "celsius"}),), ("-7", "WEATHER_Q7")),
    Scenario("array_numbers", "Use the sum tool on [3, 5, 11]. Report its sum and receipt code.",
             (("ow_sum", {"numbers": [3, 5, 11]}),), ("19", "SUM_R2")),
    Scenario("nested_schema", 'Use the catalogue tool with filter {"category":"books","in_stock":true}, ids ["b1","b2"], limit 2. Report its receipt code.',
             (("ow_catalog", {"filter": {"category": "books", "in_stock": True}, "ids": ["b1", "b2"], "limit": 2}),), ("CATALOG_N8",)),
    Scenario("unicode_arguments", f"Use the echo tool on the text between <text> and </text>, preserving every character. Report its receipt code. <text>{UNICODE_TEXT}</text>",
             (("ow_echo", {"text": UNICODE_TEXT}),), ("ECHO_U3",)),
    Scenario("two_tools", "Get weather for Reykjavik in celsius and sum [3, 5, 11] using their tools. Report both receipt codes. The calls are independent.",
             (("ow_weather", {"city": "Reykjavik", "unit": "celsius"}), ("ow_sum", {"numbers": [3, 5, 11]})), ("WEATHER_Q7", "SUM_R2"), ordered=False),
    Scenario("dependent_rounds", 'Look up the record ID for Ada using ow_lookup, then read that exact ID with ow_record. Report the record code.',
             (("ow_lookup", {"name": "Ada"}), ("ow_record", {"id": "fixture-record-9"})), ("CEDAR_41",)),
    Scenario("tool_error_recovery", 'Read the record ID "old-record" using ow_record. If the tool gives a replacement ID, retry with that ID. Report the final record code.',
             (("ow_record", {"id": "old-record"}), ("ow_record", {"id": "fixture-record-9"})), ("CEDAR_41",)),
)
PROVIDERS = ("google", "openai", "anthropic", "openai_responses")


class RequestLimit(RuntimeError):
    """The bounded test exhausted its request budget (never retry automatically)."""


def plain(value: Any) -> Any:
    """Snapshot SDK models without capturing clients, headers, or credentials."""
    if hasattr(value, "model_dump"):
        return plain(value.model_dump(exclude_none=True))
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, SimpleNamespace):
        return plain(vars(value))
    return copy.deepcopy(value)


def argument_errors(value: Any, schema: dict, path: str = "arguments") -> list[str]:
    """Validate the deliberately small JSON Schema subset used by these fixtures."""
    kind = schema["type"]
    valid = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }[kind]
    if not valid:
        return [f"{path}: expected {kind}"]
    errors = []
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: outside enum")
    if kind == "object":
        errors.extend(f"{path}.{key}: missing" for key in schema["required"] if key not in value)
        errors.extend(f"{path}.{key}: unexpected" for key in value if key not in schema["properties"])
        for key in value.keys() & schema["properties"].keys():
            errors.extend(argument_errors(value[key], schema["properties"][key], f"{path}.{key}"))
    if kind == "array":
        for index, item in enumerate(value):
            errors.extend(argument_errors(item, schema["items"], f"{path}[{index}]"))
    return errors


@dataclass
class Trace:
    provider: str
    model: str
    scenario: str
    requests: list[dict] = field(default_factory=list)
    responses: list[dict] = field(default_factory=list)
    executions: list[dict] = field(default_factory=list)
    answer: str = ""
    error_category: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Sandbox:
    """Only fixed, in-memory tools; no file/network/OS executor can be reached."""

    def __init__(self, trace: Trace):
        self.trace = trace

    def execute(self, name: str, arguments: dict, **_kwargs) -> str:
        errors = argument_errors(arguments, SCHEMAS[name]) if name in SCHEMAS else ["unknown tool"]
        if errors:
            result = "Error: " + "; ".join(errors)
        elif name == "ow_weather":
            result = json.dumps({"temperature": -7 if arguments["unit"] == "celsius" else 19.4, "receipt": "WEATHER_Q7"})
        elif name == "ow_sum":
            result = json.dumps({"sum": sum(arguments["numbers"]), "receipt": "SUM_R2"})
        elif name == "ow_catalog":
            result = json.dumps({"ids": arguments["ids"][:arguments["limit"]], "receipt": "CATALOG_N8"})
        elif name == "ow_echo":
            result = json.dumps({"text": arguments["text"], "receipt": "ECHO_U3"}, ensure_ascii=False)
        elif name == "ow_lookup":
            result = json.dumps({"record_id": "fixture-record-9"})
        elif arguments["id"] == "fixture-record-9":
            result = json.dumps({"record_code": "CEDAR_41"})
        else:
            result = 'Error: record ID is outdated. Retry ow_record with id "fixture-record-9".'
        self.trace.executions.append({"name": name, "arguments": plain(arguments), "result": result, "validation_errors": errors})
        return result


class RecordedStream:
    def __init__(self, inner, trace: Trace, request_index: int):
        self.inner, self.trace, self.request_index = inner, trace, request_index
        self.active = None

    def __enter__(self):
        self.active = self.inner.__enter__()
        return self

    def __exit__(self, *args):
        return self.inner.__exit__(*args)

    def __iter__(self):
        for item in self.active:
            self.trace.responses.append({"request": self.request_index, "payload": plain(item)})
            yield item

    @property
    def text_stream(self):
        yield from self.active.text_stream


class RecordedEndpoint:
    def __init__(self, inner, family: str, trace: Trace, consume_request, max_requests: int, max_tokens: int):
        self.inner, self.family, self.trace = inner, family, trace
        self.consume_request, self.max_requests, self.max_tokens = consume_request, max_requests, max_tokens

    def _call(self, method: str, kwargs: dict):
        if len(self.trace.requests) >= self.max_requests:
            raise RequestLimit("per-scenario request limit reached")
        self.consume_request()
        # Responses route has no max-output argument in production; cap test spend at the SDK boundary.
        if self.family == "responses":
            kwargs = {**kwargs, "max_output_tokens": self.max_tokens}
        index = len(self.trace.requests)
        self.trace.requests.append({"family": self.family, "method": method, "kwargs": plain(kwargs)})
        result = getattr(self.inner, method)(**kwargs)
        if method == "stream" or kwargs.get("stream"):
            return RecordedStream(result, self.trace, index)
        self.trace.responses.append({"request": index, "payload": plain(result)})
        return result

    def create(self, **kwargs):
        return self._call("create", kwargs)

    def stream(self, **kwargs):
        return self._call("stream", kwargs)


def recorded_client(client, trace: Trace, consume_request, max_requests: int, max_tokens: int):
    def endpoint(inner, family):
        return RecordedEndpoint(inner, family, trace, consume_request, max_requests, max_tokens)
    if trace.provider == "anthropic":
        return SimpleNamespace(messages=endpoint(client.messages, "anthropic"))
    if trace.provider == "openai_responses":
        return SimpleNamespace(responses=endpoint(client.responses, "responses"))
    return SimpleNamespace(chat=SimpleNamespace(completions=endpoint(client.chat.completions, "chat_completions")))


def run_case(provider: str, model: str, scenario: Scenario, client, sandbox_path, *,
             consume_request=lambda: None, max_requests: int = 4, max_tokens: int = 768) -> Trace:
    """Run real production schema conversion and adapter loops with sandbox executors."""
    from core import secret_store

    trace = Trace(provider, model, scenario.id)
    sandbox = Sandbox(trace)
    # Imports must not discover/migrate personal keychain credentials or load the user's .env.
    with ExitStack() as stack:
        stack.enter_context(patch.dict("os.environ", {"OPENWAND_SETTINGS_ENV_PATH": str(sandbox_path / "test.env")}))
        stack.enter_context(patch.object(secret_store, "get_secret", return_value=""))
        from core.llm_clients import client as llm
        from core.settings_model import ToolTurnBudgets
        from core.tool_registry import ToolRegistry, ToolSpec

        registry = ToolRegistry(plugin_dir=sandbox_path / "no-plugins")
        for name, schema in SCHEMAS.items():
            registry.register_builtin(ToolSpec(name, DESCRIPTIONS[name], schema))
        stack.enter_context(patch.object(llm, "_TOOL_REGISTRY", registry))
        stack.enter_context(patch.object(llm, "_execute_model_tool", side_effect=sandbox.execute))
        stack.enter_context(patch.object(llm, "_capture_screen_b64", side_effect=RuntimeError("Real screenshots are disabled in the adapter harness")))
        stack.enter_context(patch.object(llm, "_inject_frontloaded_tool_context", side_effect=lambda context, *_args, **_kwargs: context))
        stack.enter_context(patch.object(llm, "_route_capabilities", {}))
        stack.enter_context(patch.object(llm, "_tool_turn_budget", return_value=ToolTurnBudgets(max_calls=6, max_result_chars=5000, max_total_chars=20000)))
        stack.enter_context(patch.object(llm.macos_safety, "openai_compat_tools_enabled", return_value=True))
        stack.enter_context(patch.object(llm, "_use_macos_openai_compat_non_streaming", return_value=False))
        client = recorded_client(client, trace, consume_request, max_requests, max_tokens)
        common = {"use_tools": scenario.tools_enabled, "allowed_tools": list(SCHEMAS), "system_prompt": SYSTEM}
        try:
            if provider == "anthropic":
                chunks = llm._stream_anthropic(scenario.prompt, None, model, client, max_tokens=max_tokens, **common)
            elif provider == "openai_responses":
                chunks = llm._stream_codex(scenario.prompt, model, client, **common)
            else:
                chunks = llm._stream_openai_compat(scenario.prompt, None, model, client, provider=provider, max_tokens=max_tokens, temperature=0, **common)
            trace.answer = "".join(str(chunk) for chunk in chunks if getattr(chunk, "kind", "answer") == "answer")
        except Exception as exc:  # preserve diagnostic category while keeping credentials out of artifacts
            status = getattr(exc, "status_code", None)
            if isinstance(exc, RequestLimit):
                trace.error_category = "request_budget"
            elif status in (401, 403):
                trace.error_category = "authentication"
            elif status == 429:
                trace.error_category = "rate_limit_or_quota"
            elif status is not None:
                trace.error_category = "provider_api"
            elif "timeout" in type(exc).__name__.lower() or "connection" in type(exc).__name__.lower():
                trace.error_category = "transport"
            else:
                trace.error_category = "adapter_exception"
            trace.error = f"{type(exc).__name__}" + (f" (HTTP {status})" if status else "")
    return trace


def wire_calls(trace: Trace) -> list[dict]:
    """Inspect wire calls independently of production and preserve request order."""
    calls = []
    deltas: dict[tuple[int, int], dict] = {}
    response_items = {}
    for entry in trace.responses:
        payload, request = entry["payload"], entry["request"]
        for choice in payload.get("choices", []):
            for index, call in enumerate(choice.get("message", {}).get("tool_calls", [])):
                calls.append((request, index, {"id": call.get("id", ""), "name": call.get("function", {}).get("name", ""), "arguments": call.get("function", {}).get("arguments", "")}))
            for call in choice.get("delta", {}).get("tool_calls", []):
                acc = deltas.setdefault((request, call["index"]), {"id": "", "name": "", "arguments": ""})
                acc["id"] = call.get("id") or acc["id"]
                acc["name"] += call.get("function", {}).get("name") or ""
                acc["arguments"] += call.get("function", {}).get("arguments") or ""
        for index, block in enumerate(payload.get("content", [])):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append((request, index, {"id": block.get("id", ""), "name": block.get("name", ""), "arguments": block.get("input")}))
        outputs = payload.get("output", [])
        if payload.get("type") == "response.completed":
            outputs = payload.get("response", {}).get("output", [])
        if payload.get("type") == "response.output_item.done":
            outputs = [payload.get("item", {})]
        for index, item in enumerate(outputs):
            if item.get("type") == "function_call":
                position = payload.get("output_index", index) if payload.get("type") == "response.output_item.done" else index
                response_items[(request, position)] = (request, position, {"id": item.get("call_id", ""), "name": item.get("name", ""), "arguments": item.get("arguments", "")})
    calls.extend((request, index, call) for (request, index), call in deltas.items())
    calls.extend(response_items.values())
    return [call for _request, _index, call in sorted(calls, key=lambda item: item[:2])]


def result_records(trace: Trace) -> list[tuple[str, Any]]:
    """Inspect every replay, so later correct data cannot hide an earlier mismatch."""
    links = []
    for request in trace.requests:
        kwargs = request["kwargs"]
        for message in kwargs.get("messages", []):
            if message.get("role") == "tool":
                links.append((message.get("tool_call_id", ""), message.get("content")))
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result":
                        links.append((block.get("tool_use_id", ""), block.get("content")))
        for item in kwargs.get("input", []):
            if item.get("type") == "function_call_output":
                links.append((item.get("call_id", ""), item.get("output")))
    return links


def result_links(trace: Trace) -> dict[str, Any]:
    """Return latest values for display; grading inspects all result_records."""
    return dict(result_records(trace))


def grade(trace: Trace, scenario: Scenario) -> list[dict[str, str]]:
    """Separate wire/adapter defects from model decisions and service failures."""
    issues = []

    def issue(category, detail):
        issues.append({"category": category, "detail": detail})

    def key(call):
        return json.dumps(call, sort_keys=True, ensure_ascii=False)

    if trace.error_category:
        return [{"category": trace.error_category, "detail": trace.error}]
    raw = wire_calls(trace)
    executed = [(entry["name"], entry["arguments"]) for entry in trace.executions]
    normalized, valid_calls, ids = [], [], []
    for call in raw:
        ids.append(call["id"])
        try:
            args = json.loads(call["arguments"]) if isinstance(call["arguments"], str) else call["arguments"]
        except (ValueError, TypeError):
            issue("provider_protocol", f"{call['name']}: invalid JSON arguments from provider")
            continue
        if not isinstance(args, dict):
            issue("provider_protocol", f"{call['name']}: arguments are not an object")
            continue
        normalized.append((call["name"], args))
        valid_calls.append({**call, "arguments": args})
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        issue("provider_protocol", "empty or duplicate tool call IDs")
    # Unavailable tools are model decisions; adapters may safely reject them.
    known_normalized = [call for call in normalized if call[0] in SCHEMAS]
    known_executed = [call for call in executed if call[0] in SCHEMAS]
    provider_invalid = any(item["category"] == "provider_protocol" for item in issues)
    if not provider_invalid and sorted(map(key, known_normalized)) != sorted(map(key, known_executed)):
        issue("adapter_protocol", "valid wire tool calls differ from executed names/arguments")
    elif provider_invalid and any(call not in normalized for call in known_executed):
        issue("adapter_protocol", "malformed provider input was converted into an executable call")
    records = result_records(trace)
    links = dict(records)
    if set(links) - set(ids):
        issue("adapter_protocol", "tool result refers to an unknown call ID")
    for call in valid_calls:
        if provider_invalid or call["name"] not in SCHEMAS:
            continue
        if call["id"] not in links:
            issue("adapter_protocol", f"tool result missing from next request: {call['name']}")
            continue
        matches = [e for e in trace.executions if e["name"] == call["name"] and e["arguments"] == call["arguments"]]
        for call_id, content in records:
            if call_id == call["id"] and matches and content not in [e["result"] for e in matches]:
                issue("adapter_protocol", f"wrong result content linked to {call['name']}")
                break
    if not any(item["category"] == "provider_protocol" for item in issues):
        if any(argument_errors(args, SCHEMAS[name]) for name, args in normalized if name in SCHEMAS):
            issue("model_arguments", "model supplied arguments outside the fixture schema")
        actual = normalized if scenario.ordered else sorted(normalized, key=key)
        expected = list(scenario.expected_calls) if scenario.ordered else sorted(scenario.expected_calls, key=key)
        if actual != expected:
            issue("model_tool_selection", "wire tool names, arguments, count, or required order differ from the scenario")
    if not any(item["category"] in {"provider_protocol", "adapter_protocol"} for item in issues):
        if scenario.answer_exact is not None and trace.answer.strip() != scenario.answer_exact:
            issue("model_answer", "final answer did not match the requested exact response")
        for token in scenario.answer_contains:
            if token not in trace.answer:
                issue("model_answer", f"final answer is missing {token!r}")
    return issues
