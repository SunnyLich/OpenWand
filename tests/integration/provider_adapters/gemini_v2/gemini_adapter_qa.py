"""Bounded synthetic QA of OpenWand's patched Google compatibility adapter.

Offline by default. Live use requires --live --confirm-free-tier and an existing
Google_API_Key in the process environment. No key is copied to a file.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO = Path(os.environ.get("OPENWAND_QA_REPO", str(Path(__file__).resolve().parents[4])))
MODEL = "gemini-3.5-flash-lite"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/openai/"
EXPECTED_COMMIT = "24aafe1ee34a9830d686f716e391008dce383fcc"
MAX_REQUESTS = 20
MAX_OUTPUT_TOKENS = 256
MIN_INTERVAL_SECONDS = 15
SYSTEM = "You are testing synthetic tools. Follow the user's instructions exactly. Use only the offered functions. Never invent a function result. Keep the final answer short."
KEY = ""



def sanitized(value):
    """Remove secrets and URL queries before results are saved or displayed."""
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if KEY:
        encoded = encoded.replace(KEY, "[REDACTED]")
    encoded = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED]", encoded)
    encoded = re.sub(r"(https?://[^\s\"?]+)\?[^\s\"]+", r"\1?[REDACTED]", encoded)
    def hide_signatures(item):
        """Keep opaque provider signatures in memory, not in saved evidence."""
        if isinstance(item, dict):
            return {k: "[PRESENT; REDACTED]" if k == "thought_signature" else hide_signatures(v) for k, v in item.items()}
        if isinstance(item, list):
            return [hide_signatures(v) for v in item]
        return item
    return hide_signatures(json.loads(encoded))


def obj(properties=None, required=None):
    """Build a JSON object schema used by synthetic tools."""
    props = properties or {}
    return {"type": "object", "properties": props, "required": list(props) if required is None else required, "additionalProperties": False}


STRING = {"type": "string"}
SPECS = {
    "qa_lookup": ("Look up a synthetic label by code.", obj({"code": STRING})),
    "qa_inventory": ("Return synthetic stock quantity for a SKU.", obj({"sku": STRING})),
    "qa_weather": ("Return synthetic weather for a city.", obj({"city": STRING})),
    "qa_record": ("Validate a synthetic structured record without saving anything.", obj({
        "profile": obj({"name": STRING, "active": {"type": "boolean"}}),
        "items": {"type": "array", "items": obj({"sku": STRING, "quantity": {"type": "integer"}})},
        "priority": {"type": "string", "enum": ["low", "high"]}})),
    "qa_marker": ("Return a hidden synthetic marker for a slot.", obj({"slot": STRING})),
    "qa_alpha": ("Return the synthetic alpha value.", obj()),
    "qa_beta": ("Return the synthetic beta value.", obj()),
    "qa_resolve": ("Resolve a synthetic alias into an ID needed by qa_detail.", obj({"alias": STRING})),
    "qa_detail": ("Look up a synthetic label for the ID returned by qa_resolve.", obj({"id": STRING})),
    "qa_failure": ("Return a simulated unavailable error. No real external action.", obj()),
}


def scenarios():
    """Return fresh scenario definitions, expected calls, and exact output checks."""
    return [
        {"name": "no_tools", "tools": [], "prompt": "Reply with exactly READY.", "expected": [], "final": "READY", "budget": 1},
        {"name": "single_tool", "tools": ["qa_lookup"], "prompt": "Call qa_lookup once with code A. Reply with only the returned label.", "expected": [("qa_lookup", {"code": "A"})], "final": "ALPHA_41", "budget": 2},
        {"name": "distinct_selection", "tools": ["qa_inventory", "qa_weather"], "prompt": "Use the inventory tool to get stock for SKU P7. Do not request weather. Reply with only the quantity.", "expected": [("qa_inventory", {"sku": "P7"})], "final": "12", "budget": 2},
        {"name": "structured_arguments", "tools": ["qa_record"], "prompt": 'Call qa_record once with profile {"name":"Nia","active":true}, items [{"sku":"A1","quantity":2}], and priority "high". Reply with only its status.', "expected": [("qa_record", {"profile": {"name": "Nia", "active": True}, "items": [{"sku": "A1", "quantity": 2}], "priority": "high"})], "final": "ACCEPTED", "budget": 2},
        {"name": "synthetic_result_roundtrip", "tools": ["qa_marker"], "prompt": "Call qa_marker once with slot blue. Its marker is unknown until the tool returns. Reply with only that marker.", "expected": [("qa_marker", {"slot": "blue"})], "final": "ORCHID_47", "budget": 2},
        {"name": "multiple_tools", "tools": ["qa_alpha", "qa_beta"], "prompt": "Call both qa_alpha and qa_beta, each once, together in the same turn. After both results, reply with their values in alpha,beta order, separated by a comma and no spaces.", "expected": [("qa_alpha", {}), ("qa_beta", {})], "final": "17,29", "budget": 3, "parallel": True},
        {"name": "multiround_tools", "tools": ["qa_resolve", "qa_detail"], "prompt": "First call qa_resolve with alias north. Wait for its ID, then call qa_detail using that exact returned ID. Reply with only the label returned by qa_detail.", "expected": [("qa_resolve", {"alias": "north"}), ("qa_detail", {"id": "item-73"})], "final": "CEDAR", "budget": 3},
        {"name": "synthetic_tool_error", "tools": ["qa_failure"], "prompt": "Call qa_failure exactly once. If it returns an error, do not retry; reply with exactly UNAVAILABLE.", "expected": [("qa_failure", {})], "final": "UNAVAILABLE", "budget": 2},
        {"name": "unused_tool", "tools": ["qa_lookup"], "prompt": "Without using any tool, compute 2+2 and reply with only the number.", "expected": [], "final": "4", "budget": 1},
    ]


def validate(schema, value):
    """Validate the small JSON-schema subset used by these synthetic fixtures."""
    kind = schema["type"]
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if type(value) is not types[kind]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    if kind == "object":
        return set(schema["required"]).issubset(value) and set(value).issubset(schema["properties"]) and all(validate(schema["properties"][k], v) for k, v in value.items())
    if kind == "array":
        return all(validate(schema["items"], item) for item in value)
    return True


def fixture_result(name, args):
    """Return synthetic data without network, filesystem, or desktop actions."""
    return {
        "qa_lookup": {"label": "ALPHA_41"}, "qa_inventory": {"quantity": 12},
        "qa_weather": {"weather": "sunny"}, "qa_record": {"status": "ACCEPTED"},
        "qa_marker": {"marker": "ORCHID_47"}, "qa_alpha": {"value": 17},
        "qa_beta": {"value": 29}, "qa_resolve": {"id": "item-73"},
        "qa_detail": {"label": "CEDAR"} if args.get("id") == "item-73" else {"error": "BAD_SYNTHETIC_ID"},
        "qa_failure": {"error": "SIMULATED_UNAVAILABLE"},
    }[name]


def registry_for(case, calls):
    """Install real ToolSpecs with effect-free handlers and record their inputs."""
    from core.tool_registry import ToolRegistry, ToolSpec

    registry = ToolRegistry(plugin_dir=REPO / ".tmp" / "gemini-qa-no-plugins")
    registry._scripts = {}
    for name in case["tools"]:
        description, schema = SPECS[name]

        def execute(args, tool_name=name, tool_schema=schema):
            """Record one synthetic call and supply a bounded fixture response."""
            valid = validate(tool_schema, args)
            result = fixture_result(tool_name, args) if valid else {"error": "INVALID_SYNTHETIC_ARGUMENTS"}
            calls.append({"name": tool_name, "arguments": copy.deepcopy(args), "schema_valid": valid, "result": result})
            return json.dumps(result)

        registry.register_builtin(ToolSpec(name, description, schema, executor=execute, source="qa-synthetic"))
    return registry


class StopRun(BaseException):
    """Abort before the adapter can retry or switch route after an API error."""

    def __init__(self, detail):
        """Retain only sanitized error metadata."""
        self.detail = sanitized(detail)
        super().__init__(self.detail.get("kind", "stopped"))


class Gate:
    """Enforce exact model, small payload, token cap, request cap and pacing."""

    def __init__(self, live=False, prior_requests=0):
        """Start a new run counter with no earlier request."""
        self.live = live
        self.count = prior_requests
        self.last_started = 0.0
        self.stopped = False

    def allow(self, kwargs):
        """Reject unsupported work before any outgoing request is sent."""
        if self.stopped or self.count >= MAX_REQUESTS:
            raise StopRun({"kind": "request_cap_or_stopped"})
        if kwargs.get("model") != MODEL or kwargs.get("max_tokens") != MAX_OUTPUT_TOKENS:
            raise StopRun({"kind": "model_or_output_cap_violation"})
        if len(json.dumps(kwargs)) > 24000 or kwargs.get("n", 1) != 1:
            raise StopRun({"kind": "payload_or_candidate_cap_violation"})
        if set(kwargs) - {"model", "messages", "stream", "temperature", "max_tokens", "tools", "parallel_tool_calls", "stream_options"}:
            raise StopRun({"kind": "unexpected_request_option"})
        if self.live and self.last_started:
            time.sleep(max(0, MIN_INTERVAL_SECONDS - (time.monotonic() - self.last_started)))
        self.count += 1
        self.last_started = time.monotonic()


def response_summary(response):
    """Collect content, usage, and tool metadata while omitting opaque extras."""
    raw = response.model_dump(exclude_none=True)
    choices = []
    for choice in raw.get("choices", []):
        msg = choice.get("message", choice.get("delta", {}))
        calls = []
        for tc in msg.get("tool_calls", []) or []:
            calls.append({k: tc[k] for k in ("index", "id", "type", "function") if k in tc})
        choices.append({"finish_reason": choice.get("finish_reason"), "content": msg.get("content"), "tool_calls": calls})
    return sanitized({"model": raw.get("model"), "usage": raw.get("usage"), "choices": choices, "thought_signature_present": "thought_signature" in json.dumps(raw)})


class RecordingStream:
    """Observe SDK chunks without changing what the adapter consumes."""

    def __init__(self, stream, record, gate):
        """Keep stream and bookkeeping references."""
        self.stream, self.record, self.gate = stream, record, gate

    def __enter__(self):
        """Enter the underlying response stream."""
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        """Close the underlying response stream."""
        return self.stream.__exit__(*args)

    def __iter__(self):
        """Record observed chunks and stop on interrupted transport."""
        try:
            for chunk in self.stream:
                self.record["responses"].append(response_summary(chunk))
                yield chunk
        except Exception as exc:
            self.gate.stopped = True
            error = {"kind": type(exc).__name__, "status_code": getattr(exc, "status_code", None), "message": str(exc)}
            self.record["error"] = sanitized(error)
            raise StopRun(error) from None


class RecordingClient:
    """Wrap the production-created SDK client, adding usage reporting only."""

    def __init__(self, sdk, gate, records, case_budget):
        """Expose the OpenAI chat-completions interface expected by OpenWand."""
        self.sdk, self.gate, self.records, self.case_budget = sdk, gate, records, case_budget
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        """Send one bounded call with no retry and record the sanitized result."""
        if len(self.records) >= self.case_budget:
            raise StopRun({"kind": "scenario_generation_cap"})
        actual = copy.deepcopy(kwargs)
        if actual.get("stream"):
            actual["stream_options"] = {"include_usage": True}
        self.gate.allow(actual)
        record = {"request_number": self.gate.count, "request": sanitized(actual), "responses": []}
        self.records.append(record)
        try:
            response = self.sdk.chat.completions.create(**actual)
            if actual.get("stream"):
                return RecordingStream(response, record, self.gate)
            record["responses"].append(response_summary(response))
            return response
        except Exception as exc:
            self.gate.stopped = True
            error = {"kind": type(exc).__name__, "status_code": getattr(exc, "status_code", None), "message": str(exc)}
            record["error"] = sanitized(error)
            raise StopRun(error) from None


def grade(case, calls, final, records, error):
    """Grade tool contract separately from literal final-answer compliance."""
    observed = [(c["name"], c["arguments"]) for c in calls]
    expected = case["expected"]
    def normalize(xs):
        return sorted(json.dumps(x, sort_keys=True) for x in xs)
    matching = normalize(observed) == normalize(expected) if case.get("parallel") else observed == expected
    parallel_met = None
    if case.get("parallel") and records:
        first_calls = [tc for response in records[0]["responses"] for choice in response["choices"] for tc in choice["tool_calls"] if tc.get("function", {}).get("name")]
        parallel_met = {tc["function"]["name"] for tc in first_calls} == {name for name, _ in expected}
    contract = matching and all(c["schema_valid"] for c in calls)
    return {"tool_contract": "pass" if contract and not error else "unresolved" if error else "fail", "content": "pass" if final.strip() == case["final"] and not error else "unresolved" if error else "fail", "parallel_same_turn": parallel_met, "execution_matches_expected": matching}


def run_case(case, sdk, gate):
    """Run one unchanged OpenWand adapter scenario with synthetic handlers."""
    from core.llm_clients import client as llm

    calls, records, chunks = [], [], []
    client = RecordingClient(sdk, gate, records, case["budget"])
    error = None
    adapter_log = io.StringIO()
    with patch.object(llm, "_route_capabilities", {}), patch.object(llm, "_TOOL_REGISTRY", registry_for(case, calls)), contextlib.redirect_stdout(adapter_log):
        try:
            for chunk in llm._stream_openai_compat(case["prompt"], None, MODEL, client, use_tools=bool(case["tools"]), allowed_tools=case["tools"], provider="google", max_tokens=MAX_OUTPUT_TOKENS, temperature=0, system_prompt=SYSTEM):
                chunks.append(chunk)
        except StopRun as exc:
            error = exc.detail
        except Exception as exc:
            error = sanitized({"kind": type(exc).__name__, "message": str(exc)})
            gate.stopped = True
    # OpenWand yields tagged progress separately from the final text.
    final_chunks = list(llm._stream_answer_text(iter(chunks)))
    final = "".join(final_chunks)
    result = {"scenario": case["name"], "status": "error" if error else "completed", "prompt": case["prompt"], "tools_offered": case["tools"], "expected_calls": case["expected"], "expected_final": case["final"], "calls": calls, "final": final, "chunks": chunks, "generations": len(records), "records": records, "error": error, "adapter_log": adapter_log.getvalue()}
    result.update(grade(case, calls, final, records, error))
    return sanitized(result)


def verification_cases():
    """Authorize only the parallel scenario within the two remaining requests."""
    case = next(case for case in scenarios() if case["name"] == "multiple_tools")
    case["budget"] = 2
    return [case]


def main():
    """Run once only when free-tier authorization is explicitly acknowledged."""
    global KEY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--confirm-free-tier", action="store_true")
    parser.add_argument("--prior-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("results.json"))
    args = parser.parse_args()
    if not args.live or not args.confirm_free_tier:
        parser.error("Live QA requires --live --confirm-free-tier; run offline tests first.")
    if args.output.exists():
        parser.error("Refusing to overwrite an existing run; outcomes must be preserved.")
    prior = json.loads(args.prior_results.read_text())
    prior_count = prior["generation_requests"]
    if prior_count != 18 or prior["model"] != MODEL:
        parser.error("Expected eighteen cumulative requests as prior evidence.")
    import subprocess
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    if commit != EXPECTED_COMMIT:
        parser.error("Checkout differs from the reviewed commit.")
    KEY = os.environ.get("Google_API_Key", "")
    if not KEY:
        parser.error("Google_API_Key is missing or empty.")
    from core import secret_store

    with patch.object(secret_store, "get_secret", return_value=""), patch.object(secret_store, "refresh_cache"):
        import config
        from core.llm_clients import client as llm

    config.GOOGLE_API_KEY = KEY
    with patch.object(llm, "_OPENAI_MAX_RETRIES", 0):
        sdk = llm._build_dynamic_openai_client("google")
    sdk = sdk.with_options(max_retries=0, timeout=30)
    if str(sdk.base_url) != ENDPOINT or sdk.max_retries != 0:
        parser.error("Unexpected endpoint or retries.")
    sdk._client.follow_redirects = False
    gate = Gate(live=True, prior_requests=prior_count)
    report = {"kind": "new Gemini supplement; prior suite not downloaded", "commit": commit, "model": MODEL, "route": ENDPOINT + "chat/completions", "credential_name": "Google_API_Key", "limits": {"generations": MAX_REQUESTS, "output_tokens_per_generation": MAX_OUTPUT_TOKENS, "min_interval_seconds": MIN_INTERVAL_SECONDS, "retries": 0}, "free_tier_basis": "User confirmed account is Free Tier; current official pricing lists model input/output free. Billing dashboard not independently inspected.", "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "runs": []}
    try:
        report["kind"] = "parallel-call fix verification; all prior evidence preserved separately"
        report["prior_generation_requests"] = prior_count
        report["product_patch_sha256"] = __import__("hashlib").sha256(subprocess.check_output(["git", "diff", "--", "core/llm_clients/client.py"], cwd=REPO) + (REPO / "core/llm_clients/tool_call_metadata.py").read_bytes()).hexdigest()
        for case in verification_cases():
            if gate.stopped:
                result = {"scenario": case["name"], "status": "skipped", "reason": "Run halted after earlier provider or transport error; no retry or model switch.", "generations": 0}
            else:
                print(json.dumps({"starting": case["name"], "requests_so_far": gate.count}), flush=True)
                result = run_case(case, sdk, gate)
            report["runs"].append(result)
            report["generation_requests"] = gate.count
            report["new_generation_requests"] = gate.count - prior_count
            args.output.write_text(json.dumps(sanitized(report), ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({k: result[k] for k in ("scenario", "status", "generations", "tool_contract", "content", "error") if k in result}), flush=True)
    finally:
        sdk.close()
        config.GOOGLE_API_KEY = ""
    report["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.output.write_text(json.dumps(sanitized(report), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
