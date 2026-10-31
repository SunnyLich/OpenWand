"""Offline self-tests for the opt-in provider matrix and its diagnostic grader.

Only SDK-shaped in-memory endpoints are used. Socket connections, SDK client
construction, keychain access, and production tool execution are forbidden.
The production adapters and their schema conversion remain real.
"""
from __future__ import annotations

import json
import socket
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from support.provider_adapter_matrix import (
    PROVIDERS,
    SCENARIOS,
    SCHEMAS,
    UNICODE_TEXT,
    RecordedEndpoint,
    RequestLimit,
    Sandbox,
    Scenario,
    Trace,
    argument_errors,
    grade,
    plain,
    result_links,
    run_case,
    wire_calls,
)

_MODEL = "offline-harness-model"
_CASES = {scenario.id: scenario for scenario in SCENARIOS}


class _Stream:
    def __init__(self, events=(), *, text=()):
        self.events = list(events)
        self.text = list(text)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True
        return False

    def __iter__(self):
        return iter(self.events)

    @property
    def text_stream(self):
        yield from self.text


class _Endpoint:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def _call(self, method, kwargs):
        self.calls.append({"method": method, "kwargs": deepcopy(kwargs)})
        result = next(self.replies)
        if isinstance(result, Exception):
            raise result
        return result

    def create(self, **kwargs):
        return self._call("create", kwargs)

    def stream(self, **kwargs):
        return self._call("stream", kwargs)


def _client(provider, endpoint):
    if provider == "anthropic":
        return SimpleNamespace(messages=endpoint)
    if provider == "openai_responses":
        return SimpleNamespace(responses=endpoint)
    return SimpleNamespace(chat=SimpleNamespace(completions=endpoint))


def _chunk(*calls, text=None, finish=None):
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=text, tool_calls=list(calls)),
        finish_reason=finish,
    )])


def _delta(index, *, call_id=None, name=None, arguments=None):
    return SimpleNamespace(index=index, id=call_id, function=SimpleNamespace(
        name=name, arguments=arguments,
    ))


def _reply(provider, calls=(), *, text="", first=False, tools=True):
    """Calls are (id, name, arguments) triples with deterministic JSON data."""
    if provider in {"google", "openai"}:
        if first:
            events = [_chunk(text="Inspecting synthetic fixtures.")] if calls else []
            # Interleave chunks and split both function names and JSON strings.
            for index, (call_id, name, args) in enumerate(calls):
                encoded = json.dumps(args, ensure_ascii=True)
                events.append(_chunk(_delta(index, call_id=call_id, name=name[:3], arguments=encoded[:5])))
            for index, (_call_id, name, args) in reversed(list(enumerate(calls))):
                encoded = json.dumps(args, ensure_ascii=True)
                events.append(_chunk(_delta(index, name=name[3:], arguments=encoded[5:])))
            events.append(_chunk(text=text or None, finish="tool_calls" if calls else "stop"))
            return _Stream(events)
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="tool_calls" if calls else "stop",
            message=SimpleNamespace(content=text, tool_calls=[
                SimpleNamespace(id=call_id, type="function", function=SimpleNamespace(
                    name=name, arguments=json.dumps(args, ensure_ascii=True),
                )) for call_id, name, args in calls
            ]),
        )])
    if provider == "anthropic":
        if not tools:
            return _Stream(text=[text])
        return SimpleNamespace(content=[
            *([SimpleNamespace(type="text", text=text)] if text else []),
            *(SimpleNamespace(type="tool_use", id=call_id, name=name, input=deepcopy(args))
              for call_id, name, args in calls),
        ], stop_reason="tool_use" if calls else "end_turn")
    if not tools:
        return _Stream([
            SimpleNamespace(type="response.reasoning_text.delta", delta="Private synthetic thought."),
            SimpleNamespace(type="response.output_text.delta", delta=text),
        ])
    return SimpleNamespace(id="response-fixture", output_text=text, output=[
        {"type": "function_call", "id": f"item-{call_id}", "call_id": call_id,
         "name": name, "arguments": json.dumps(args, ensure_ascii=True)}
        for call_id, name, args in calls
    ])


def _scenario_endpoint(provider, scenario):
    calls = [(f"call-{index}", name, deepcopy(args))
             for index, (name, args) in enumerate(scenario.expected_calls)]
    groups = [[call] for call in calls] if scenario.ordered else [calls]
    replies = [_reply(provider, group, first=index == 0)
               for index, group in enumerate(groups) if group]
    replies.append(_reply(provider, text=" ".join(scenario.answer_contains),
                          first=not calls, tools=scenario.tools_enabled))
    return _Endpoint(replies)


@pytest.fixture(autouse=True)
def _offline_only(monkeypatch, tmp_path):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("The provider harness self-tests must remain offline")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setenv("OPENWAND_SETTINGS_ENV_PATH", str(tmp_path / "settings.env"))
    monkeypatch.setenv("CHAT_TOOL_TRACE_UI", "0")
    from core import secret_store
    from core.system import sdk_clients

    monkeypatch.setattr(secret_store, "get_secret", lambda *_a, **_kw: "")
    monkeypatch.setattr(sdk_clients, "openai_client", forbidden)
    monkeypatch.setattr(sdk_clients, "anthropic_client", forbidden)
    from core.llm_clients import client as llm

    monkeypatch.setattr(llm, "_execute_model_tool", forbidden)
    monkeypatch.setattr(llm.config, "CHAT_REASONING_EFFORT", "")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.id)
def test_scenarios_only_expect_schema_valid_synthetic_tools(scenario):
    for name, arguments in scenario.expected_calls:
        assert name in SCHEMAS
        assert argument_errors(arguments, SCHEMAS[name]) == []
    assert scenario.tools_enabled or not scenario.expected_calls


@pytest.mark.parametrize("name,arguments,expected", [
    ("ow_weather", {"city": "Reykjavik", "unit": "celsius"}, {"temperature": -7, "receipt": "WEATHER_Q7"}),
    ("ow_weather", {"city": "Reykjavik", "unit": "fahrenheit"}, {"temperature": 19.4, "receipt": "WEATHER_Q7"}),
    ("ow_sum", {"numbers": [3, 5, 11]}, {"sum": 19, "receipt": "SUM_R2"}),
    ("ow_catalog", {"filter": {"category": "books", "in_stock": True}, "ids": ["b1", "b2"], "limit": 1}, {"ids": ["b1"], "receipt": "CATALOG_N8"}),
    ("ow_echo", {"text": UNICODE_TEXT}, {"text": UNICODE_TEXT, "receipt": "ECHO_U3"}),
    ("ow_lookup", {"name": "Ada"}, {"record_id": "fixture-record-9"}),
    ("ow_record", {"id": "fixture-record-9"}, {"record_code": "CEDAR_41"}),
], ids=["celsius", "fahrenheit", "sum", "catalogue", "unicode", "lookup", "record"])
def test_sandbox_returns_fixed_fixture_results(name, arguments, expected):
    trace = Trace("offline", _MODEL, "sandbox")
    result = Sandbox(trace).execute(name, arguments)
    assert json.loads(result) == expected
    assert trace.executions == [{
        "name": name, "arguments": arguments, "result": result, "validation_errors": [],
    }]
    arguments.clear()
    assert trace.executions[0]["arguments"]


@pytest.mark.parametrize("name,arguments,error", [
    ("run_shell", {"command": "never execute"}, "unknown tool"),
    ("ow_weather", {}, "arguments.city: missing"),
    ("ow_weather", {"city": "Reykjavik", "unit": "kelvin"}, "arguments.unit: outside enum"),
    ("ow_echo", {"text": 3}, "arguments.text: expected string"),
    ("ow_echo", {"text": "hello", "extra": "field"}, "arguments.extra: unexpected"),
    ("ow_sum", {"numbers": "3,5,11"}, "arguments.numbers: expected array"),
    ("ow_sum", {"numbers": [3, True]}, "arguments.numbers[1]: expected number"),
    ("ow_catalog", {"filter": {"category": "books", "in_stock": 1}, "ids": ["b1"], "limit": 2}, "arguments.filter.in_stock: expected boolean"),
    ("ow_catalog", {"filter": {"category": "books", "in_stock": True}, "ids": ["b1"], "limit": True}, "arguments.limit: expected integer"),
    ("ow_echo", ["not an object"], "arguments: expected object"),
])
def test_sandbox_rejects_unknown_tools_and_invalid_arguments(name, arguments, error):
    trace = Trace("offline", _MODEL, "sandbox")
    result = Sandbox(trace).execute(name, arguments)
    assert result.startswith("Error: ")
    assert error in result
    assert error in trace.executions[0]["validation_errors"]


def test_sandbox_outdated_record_is_recoverable_tool_error():
    trace = Trace("offline", _MODEL, "sandbox")
    sandbox = Sandbox(trace)
    assert sandbox.execute("ow_record", {"id": "old-record"}).startswith("Error: record ID is outdated")
    assert not trace.executions[0]["validation_errors"]
    assert json.loads(sandbox.execute("ow_record", {"id": "fixture-record-9"})) == {"record_code": "CEDAR_41"}


def test_plain_snapshots_nested_sdk_models_without_aliasing():
    class _Model:
        def __init__(self):
            self.payload = {"content": [SimpleNamespace(type="text", text=UNICODE_TEXT)]}

        def model_dump(self, *, exclude_none):
            assert exclude_none is True
            return self.payload

    source = _Model()
    snapshot = plain({"response": source, "tuple": (1, 2)})
    source.payload["content"][0].text = "changed"
    assert snapshot == {"response": {"content": [{"type": "text", "text": UNICODE_TEXT}]}, "tuple": [1, 2]}


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.id)
def test_run_case_production_routes_pass_all_synthetic_scenarios(provider, scenario, tmp_path):
    endpoint = _scenario_endpoint(provider, scenario)
    consume = Mock()
    trace = run_case(provider, _MODEL, scenario, _client(provider, endpoint), tmp_path,
                     consume_request=consume, max_tokens=321)
    assert not trace.error_category, trace.to_dict()
    assert grade(trace, scenario) == []
    assert trace.answer == " ".join(scenario.answer_contains)
    assert "Inspecting synthetic fixtures." not in trace.answer
    assert "Private synthetic thought." not in trace.answer
    assert consume.call_count == len(endpoint.calls) == len(trace.requests)
    assert 1 <= len(endpoint.calls) <= 3
    assert len(wire_calls(trace)) == len(scenario.expected_calls)
    assert len(result_links(trace)) == len(scenario.expected_calls)
    for request in trace.requests:
        kwargs = request["kwargs"]
        if provider == "openai_responses":
            assert kwargs["max_output_tokens"] == 321
        else:
            assert kwargs.get("max_tokens", kwargs.get("max_completion_tokens")) == 321
        if not scenario.tools_enabled:
            assert not kwargs.get("tools")
        else:
            tools = kwargs["tools"]
            by_name = {tool["function"]["name"] if "function" in tool else tool["name"]: tool for tool in tools}
            assert set(by_name) == set(SCHEMAS)
            for name, tool in by_name.items():
                schema = tool["function"]["parameters"] if "function" in tool else tool.get("input_schema", tool.get("parameters"))
                assert schema == SCHEMAS[name]


def _trace_for(scenario, provider="openai"):
    """Build independently valid wire/execution/result transcripts for grading."""
    trace = Trace(provider, _MODEL, scenario.id, answer=" ".join(scenario.answer_contains))
    calls = [(f"call-{index}", name, deepcopy(arguments))
             for index, (name, arguments) in enumerate(scenario.expected_calls)]
    payload = _reply(provider, calls)
    trace.responses.append({"request": 0, "payload": plain(payload)})
    sandbox = Sandbox(trace)
    outputs = [(call_id, sandbox.execute(name, arguments)) for call_id, name, arguments in calls]
    if provider == "anthropic":
        kwargs = {"messages": [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call_id, "content": content}
            for call_id, content in outputs
        ]}]}
    elif provider == "openai_responses":
        kwargs = {"input": [{"type": "function_call_output", "call_id": call_id, "output": content}
                            for call_id, content in outputs]}
    else:
        kwargs = {"messages": [{"role": "tool", "tool_call_id": call_id, "content": content}
                               for call_id, content in outputs]}
    trace.requests = [{"family": provider, "method": "create", "kwargs": {}},
                      {"family": provider, "method": "create", "kwargs": kwargs}]
    return trace


def _categories(trace, scenario):
    return {issue["category"] for issue in grade(trace, scenario)}


@pytest.mark.parametrize("provider", ["openai", "anthropic", "openai_responses"])
@pytest.mark.parametrize("defect", ["swapped_results", "unknown_result_id", "missing_result", "changed_execution", "lost_execution"])
def test_grade_detects_adapter_corruption_without_blame_for_model_selection(provider, defect):
    scenario = _CASES["two_tools"]
    trace = _trace_for(scenario, provider)
    assert grade(trace, scenario) == []
    kwargs = trace.requests[-1]["kwargs"]
    if provider == "anthropic":
        results = kwargs["messages"][0]["content"]
        id_key, content_key = "tool_use_id", "content"
    elif provider == "openai_responses":
        results = kwargs["input"]
        id_key, content_key = "call_id", "output"
    else:
        results = kwargs["messages"]
        id_key, content_key = "tool_call_id", "content"
    if defect == "swapped_results":
        results[0][content_key], results[1][content_key] = results[1][content_key], results[0][content_key]
    elif defect == "unknown_result_id":
        results[0][id_key] = "not-a-provider-call"
    elif defect == "missing_result":
        results.pop()
    elif defect == "changed_execution":
        trace.executions[0]["arguments"]["city"] = "Wrong city"
    else:
        trace.executions.pop()
    categories = _categories(trace, scenario)
    assert "adapter_protocol" in categories
    assert "model_tool_selection" not in categories


def test_grade_missing_tool_decision_is_model_selection_not_adapter_loss():
    scenario = _CASES["weather"]
    trace = Trace("openai", _MODEL, scenario.id, answer="-7 WEATHER_Q7")
    assert _categories(trace, scenario) == {"model_tool_selection"}


@pytest.mark.parametrize("name,arguments", [
    ("ow_echo", {"text": "unexpected choice"}),
    ("ow_weather", {"city": "Paris", "unit": "celsius"}),
    ("unknown_tool", {}),
    ("ow_weather", {"city": "Reykjavik", "unit": "kelvin"}),
])
def test_grade_wrong_tool_or_arguments_is_a_model_decision(name, arguments):
    scenario = _CASES["weather"]
    wrong = Scenario("wrong", "fixture", ((name, arguments),), scenario.answer_contains)
    trace = _trace_for(wrong)
    categories = _categories(trace, scenario)
    assert "model_tool_selection" in categories
    assert "adapter_protocol" not in categories
    if name in SCHEMAS and argument_errors(arguments, SCHEMAS[name]):
        assert "model_arguments" in categories


@pytest.mark.parametrize("arguments", ['{"city":', '[]', '"scalar"', 'null', '17'])
def test_grade_provider_malformed_wire_arguments_are_not_adapter_loss(arguments):
    scenario = _CASES["weather"]
    trace = Trace("openai", _MODEL, scenario.id)
    trace.responses = [{"request": 0, "payload": {"choices": [{"message": {"tool_calls": [{
        "id": "bad-call", "function": {"name": "ow_weather", "arguments": arguments},
    }]}}]}}]
    categories = _categories(trace, scenario)
    assert "provider_protocol" in categories
    assert "adapter_protocol" not in categories


@pytest.mark.parametrize("provider", ["openai", "anthropic", "openai_responses"])
@pytest.mark.parametrize("ids", [("", "call-1"), ("duplicate", "duplicate")])
def test_grade_rejects_empty_or_duplicate_call_ids(provider, ids):
    scenario = _CASES["two_tools"]
    trace = _trace_for(scenario, provider)
    payload = trace.responses[0]["payload"]
    calls = payload["output"] if provider == "openai_responses" else (payload["content"] if provider == "anthropic" else payload["choices"][0]["message"]["tool_calls"])
    for call, call_id in zip(calls, ids, strict=True):
        call["call_id" if provider == "openai_responses" else "id"] = call_id
    assert "provider_protocol" in _categories(trace, scenario)


def test_grade_independent_calls_allow_reverse_order_but_dependent_calls_do_not():
    independent = _CASES["two_tools"]
    reordered = Scenario("reversed", "fixture", tuple(reversed(independent.expected_calls)), independent.answer_contains)
    assert grade(_trace_for(reordered), independent) == []
    dependent = _CASES["dependent_rounds"]
    reordered = Scenario("reversed", "fixture", tuple(reversed(dependent.expected_calls)), dependent.answer_contains)
    assert "model_tool_selection" in _categories(_trace_for(reordered), dependent)


def test_wire_calls_deduplicates_responses_done_and_completed_events():
    item = {"type": "function_call", "call_id": "call-1", "name": "ow_echo", "arguments": '{"text":"hello"}'}
    trace = Trace("openai_responses", _MODEL, "wire")
    trace.responses = [
        {"request": 0, "payload": {"type": "response.output_item.done", "item": deepcopy(item)}},
        {"request": 0, "payload": {"type": "response.completed", "response": {"output": [deepcopy(item)]}}},
    ]
    assert wire_calls(trace) == [{"id": "call-1", "name": "ow_echo", "arguments": '{"text":"hello"}'}]


def test_recorded_endpoint_snapshots_request_and_response_before_mutation():
    reply = SimpleNamespace(content=[SimpleNamespace(type="text", text="original")])
    inner = _Endpoint([reply])
    trace = Trace("anthropic", _MODEL, "snapshot")
    consume = Mock()
    endpoint = RecordedEndpoint(inner, "anthropic", trace, consume, 4, 321)
    messages = [{"role": "user", "content": ["original"]}]
    assert endpoint.create(messages=messages) is reply
    messages[0]["content"].append("mutated")
    reply.content[0].text = "mutated"
    assert trace.requests[0]["kwargs"]["messages"] == [{"role": "user", "content": ["original"]}]
    assert trace.responses[0]["payload"]["content"][0]["text"] == "original"
    consume.assert_called_once_with()


def test_recorded_endpoint_enforces_local_budget_before_consuming_global_budget():
    trace = Trace("openai_responses", _MODEL, "budget")
    inner = _Endpoint([SimpleNamespace(output=[])])
    consume = Mock()
    endpoint = RecordedEndpoint(inner, "responses", trace, consume, 1, 123)
    endpoint.create(input=[], max_output_tokens=9999)
    with pytest.raises(RequestLimit, match="per-scenario"):
        endpoint.create(input=[])
    consume.assert_called_once_with()
    assert len(inner.calls) == len(trace.requests) == 1
    assert inner.calls[0]["kwargs"]["max_output_tokens"] == 123


def test_recorded_endpoint_global_budget_prevents_request_and_client_access():
    trace = Trace("openai", _MODEL, "budget")
    inner = _Endpoint([])
    consume = Mock(side_effect=RequestLimit("whole-run request limit reached"))
    endpoint = RecordedEndpoint(inner, "chat_completions", trace, consume, 4, 123)
    with pytest.raises(RequestLimit, match="whole-run"):
        endpoint.create(messages=[])
    assert not inner.calls
    assert not trace.requests
    assert not trace.responses


@pytest.mark.parametrize("provider", PROVIDERS)
def test_run_case_request_budget_bounds_real_adapter_loop(provider, tmp_path):
    scenario = _CASES["dependent_rounds"]
    endpoint = _scenario_endpoint(provider, scenario)
    trace = run_case(provider, _MODEL, scenario, _client(provider, endpoint), tmp_path, max_requests=1)
    assert trace.error_category == "request_budget"
    assert len(trace.requests) == len(endpoint.calls) == 1
    assert _categories(trace, scenario) == {"request_budget"}


class _StatusError(RuntimeError):
    def __init__(self, status):
        super().__init__("synthetic-secret-marker must not be included in trace")
        self.status_code = status


class _TestTimeoutError(RuntimeError):
    pass


class _TestConnectionError(RuntimeError):
    pass


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("error,category", [
    (_StatusError(401), "authentication"),
    (_StatusError(403), "authentication"),
    (_StatusError(429), "rate_limit_or_quota"),
    (_StatusError(503), "provider_api"),
    (_TestTimeoutError("synthetic-secret-marker"), "transport"),
    (_TestConnectionError("synthetic-secret-marker"), "transport"),
    (RequestLimit("synthetic-secret-marker"), "request_budget"),
    (ValueError("synthetic-secret-marker"), "adapter_exception"),
], ids=["unauthorized", "forbidden", "quota", "api", "timeout", "connection", "budget", "adapter"])
def test_run_case_classifies_errors_without_secret_exception_text(provider, error, category, tmp_path):
    scenario = _CASES["weather"]
    endpoint = _Endpoint([error])
    trace = run_case(provider, _MODEL, scenario, _client(provider, endpoint), tmp_path)
    assert trace.error_category == category
    assert "synthetic-secret-marker" not in json.dumps(trace.to_dict())
    assert type(error).__name__ in trace.error
    assert len(endpoint.calls) == 1
    assert _categories(trace, scenario) == {category}


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_run_case_rejected_unknown_wire_tool_is_model_selection(provider, tmp_path):
    scenario = _CASES["no_tool_needed"]
    endpoint = _Endpoint([_reply(provider, [("bad-call", "unknown_tool", {})], first=True,
                                 text="adapter-ready"), _reply(provider, text="adapter-ready")])
    trace = run_case(provider, _MODEL, scenario, _client(provider, endpoint), tmp_path)
    assert not trace.error_category
    assert not trace.executions
    # Unknown calls receive a correlated denial and cannot reach any executor.
    assert _categories(trace, scenario) == {"model_tool_selection"}


def test_grade_does_not_hide_corrupt_result_behind_later_correct_replay():
    scenario = _CASES["two_tools"]
    trace = _trace_for(scenario)
    earlier = deepcopy(trace.requests[-1])
    earlier["kwargs"]["messages"][0]["content"] = "corrupted result sent to provider"
    trace.requests.insert(1, earlier)
    assert "adapter_protocol" in _categories(trace, scenario)


@pytest.mark.parametrize("provider", ["google", "openai"])
def test_run_case_blocks_screenshot_special_case_on_followup(provider, tmp_path, monkeypatch):
    from core.llm_clients import client as llm

    real_screenshot = Mock(side_effect=AssertionError("Real screenshot function must not be reached"))
    monkeypatch.setattr(llm, "_capture_screen_b64", real_screenshot)
    scenario = _CASES["weather"]
    endpoint = _Endpoint([
        _reply(provider, [("call-1", "ow_weather", {"city": "Reykjavik", "unit": "celsius"})], first=True),
        _reply(provider, [("call-2", "capture_screen", {})]),
    ])
    trace = run_case(provider, _MODEL, scenario, _client(provider, endpoint), tmp_path)
    assert trace.error_category == "adapter_exception"
    assert trace.error == "RuntimeError"
    real_screenshot.assert_not_called()
    assert llm._capture_screen_b64 is real_screenshot
    assert [item["name"] for item in trace.executions] == ["ow_weather"]


@pytest.mark.parametrize("arguments", [
    ["--live"],
    ["--live", "--provider", "google"],
    ["--live", "--provider", "google", "--model", "fixture"],
    ["--provider", "google"],
])
def test_runner_rejects_incomplete_or_ambiguous_opt_in_before_key_prompt(arguments, monkeypatch):
    from scripts import run_provider_adapter_matrix as runner

    prompt = Mock(side_effect=AssertionError("No credential prompt expected"))
    launch = Mock(side_effect=AssertionError("No pytest invocation expected"))
    monkeypatch.setattr(runner.getpass, "getpass", prompt)
    monkeypatch.setattr(pytest, "main", launch)
    with pytest.raises(SystemExit) as exc:
        runner.main(arguments)
    assert exc.value.code == 2
    prompt.assert_not_called()
    launch.assert_not_called()


def test_runner_rejects_non_tty_live_key_entry_before_prompt(monkeypatch):
    from scripts import run_provider_adapter_matrix as runner

    prompt = Mock(side_effect=AssertionError("No credential prompt expected"))
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(runner.getpass, "getpass", prompt)
    with pytest.raises(SystemExit) as exc:
        runner.main(["--live", "--provider", "google", "--model", "fixture", "--free-tier-confirmed"])
    assert exc.value.code == 2
    prompt.assert_not_called()


def test_runner_rejects_unknown_scenario_before_prompt(monkeypatch):
    from scripts import run_provider_adapter_matrix as runner

    prompt = Mock(side_effect=AssertionError("No credential prompt expected"))
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(runner.getpass, "getpass", prompt)
    with pytest.raises(SystemExit) as exc:
        runner.main(["--live", "--provider", "google", "--model", "fixture", "--free-tier-confirmed", "--scenario", "unknown"])
    assert exc.value.code == 2
    prompt.assert_not_called()


def test_runner_defaults_offline_and_isolates_state_before_pytest(monkeypatch, tmp_path):
    import os
    from pathlib import Path

    from core import secret_store
    from scripts import run_provider_adapter_matrix as runner

    observed = {}
    original_secret_lookup = secret_store.get_secret
    original_settings_path = os.environ.get("OPENWAND_SETTINGS_ENV_PATH")
    original_isolated_host = os.environ.get("OPENWAND_ISOLATED_TEST_HOST")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner.getpass, "getpass", Mock(side_effect=AssertionError("Offline mode cannot prompt for keys")))

    def fake_pytest_main(arguments):
        observed["arguments"] = arguments
        assert os.environ["OPENWAND_RUN_PROVIDER_ADAPTER_TESTS"] == "0"
        assert os.environ.get("OPENWAND_ISOLATED_TEST_HOST") == original_isolated_host
        paths = [Path(os.environ[name]) for name in (
            "OPENWAND_SETTINGS_ENV_PATH", "OPENWAND_USER_DATA_DIR", "OPENWAND_DATA_ROOT",
        )]
        assert len({path.parent for path in paths}) == 1
        assert paths[0].parent.is_dir()
        observed["temporary_root"] = paths[0].parent
        assert secret_store.get_secret("OPENAI_API_KEY") == ""
        assert secret_store.get_secret is not original_secret_lookup
        with pytest.raises(AssertionError, match="network access"):
            socket.create_connection(("provider.invalid", 443))
        return 0

    monkeypatch.setattr(pytest, "main", fake_pytest_main)
    assert runner.main(["--report-dir", str(tmp_path / "reports")]) == 0
    assert "tests/test_provider_adapter_harness.py" in observed["arguments"]
    assert "tests/test_provider_adapter_protocol.py" in observed["arguments"]
    assert "tests/test_provider_adapter_matrix.py" in observed["arguments"]
    assert "tests/integration/provider_adapters" in observed["arguments"]
    assert "tests/test_openai_provider_adapter.py" in observed["arguments"]
    assert "tests/test_gemini_provider_regressions.py" in observed["arguments"]
    assert not observed["temporary_root"].exists()
    assert os.environ.get("OPENWAND_SETTINGS_ENV_PATH") == original_settings_path
    assert secret_store.get_secret is original_secret_lookup


@pytest.mark.parametrize("provider", PROVIDERS)
def test_runner_live_opt_in_uses_only_hidden_test_key_and_selected_route(provider, monkeypatch, tmp_path):
    import os

    from scripts import run_provider_adapter_matrix as runner

    key = "synthetic-test-key-not-real"
    observed = {}
    key_variable = runner.KEY_VARIABLES[provider]
    before_key = os.environ.get(key_variable)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    prompt = Mock(return_value=key)
    monkeypatch.setattr(runner.getpass, "getpass", prompt)

    def fake_pytest_main(arguments):
        observed["arguments"] = arguments
        assert os.environ["OPENWAND_RUN_PROVIDER_ADAPTER_TESTS"] == "1"
        assert os.environ["OPENWAND_ADAPTER_FREE_TIER_CONFIRMED"] == "1"
        assert os.environ["OPENWAND_ADAPTER_PROVIDERS"] == provider
        assert os.environ[f"OPENWAND_ADAPTER_{provider.upper()}_MODEL"] == "fixture-model"
        assert os.environ[key_variable] == key
        assert key not in repr(arguments)
        return 0

    monkeypatch.setattr(pytest, "main", fake_pytest_main)
    assert runner.main(["--live", "--provider", provider, "--model", "fixture-model", "--free-tier-confirmed",
                        "--scenario", "weather", "--report-dir", str(tmp_path / "reports")]) == 0
    assert observed["arguments"][-3:] == ["tests/test_provider_adapter_matrix.py", "-k", f"{provider} and weather"]
    assert os.environ.get(key_variable) == before_key
    prompt.assert_called_once()
