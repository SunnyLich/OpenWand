"""Opt-in real provider matrix. No credentials or SDKs are loaded at collection.

Ordinary pytest skips all cases. See docs/PROVIDER_ADAPTER_TESTS.md for setup,
request limits, zero-spend restrictions, coverage, and result interpretation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from support.provider_adapter_matrix import PROVIDERS, SCENARIOS, RequestLimit, grade, run_case

pytestmark = [
    pytest.mark.real_provider_adapter,
    pytest.mark.skipif(
        os.getenv("OPENWAND_RUN_PROVIDER_ADAPTER_TESTS") != "1",
        reason="live provider tests disabled; explicit opt-in and non-billable test credentials required",
    ),
]

KEY_VARIABLES = {
    "google": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY", "openai_responses": "OPENAI_API_KEY",
}


@pytest.fixture(scope="module")
def live_budget(request):
    if os.getenv("OPENWAND_ADAPTER_FREE_TIER_CONFIRMED") != "1":
        pytest.fail("Confirm the selected API key cannot incur charges before setting OPENWAND_ADAPTER_FREE_TIER_CONFIRMED=1.")
    if getattr(request.config.option, "numprocesses", None):
        pytest.fail("Run this budgeted matrix serially, without pytest-xdist.")
    providers = [item.strip() for item in os.getenv("OPENWAND_ADAPTER_PROVIDERS", "").split(",") if item.strip()]
    if not providers or len(providers) != len(set(providers)) or set(providers) - set(PROVIDERS):
        pytest.fail(f"Set OPENWAND_ADAPTER_PROVIDERS to a unique comma-separated subset of {PROVIDERS}.")
    # Deliberately not configurable upwards: <= 4 SDK calls/case, <= 36/provider.
    state = {"remaining": 36 * len(providers)}

    def consume():
        if state["remaining"] <= 0:
            raise RequestLimit("whole-run request limit reached")
        state["remaining"] -= 1

    return providers, consume


@pytest.fixture(scope="module", params=PROVIDERS)
def live_route(request, live_budget):
    provider = request.param
    providers, consume = live_budget
    if provider not in providers:
        pytest.skip(f"provider {provider} not selected")
    model_var = f"OPENWAND_ADAPTER_{provider.upper()}_MODEL"
    model = os.getenv(model_var, "").strip()
    if not model:
        pytest.fail(f"Selected provider requires an explicit model ID in {model_var}; no paid model is chosen by default.")
    key_var = KEY_VARIABLES[provider]
    key = os.getenv(key_var, "").strip()
    if not key:
        pytest.fail(f"Selected provider requires {key_var}; missing credentials are not a pass.")
    from core.system import sdk_clients

    # Explicit official URLs ignore unrelated OPENAI_BASE_URL/ANTHROPIC_BASE_URL settings.
    kwargs = {"api_key": key, "timeout": 30.0, "max_retries": 0}
    if provider == "anthropic":
        client = sdk_clients.anthropic_client(base_url="https://api.anthropic.com", **kwargs)
    else:
        base_url = "https://generativelanguage.googleapis.com/v1beta/openai/" if provider == "google" else "https://api.openai.com/v1"
        client = sdk_clients.openai_client(base_url=base_url, **kwargs)
    yield provider, model, client, consume, key
    client.close()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.id)
def test_live_provider_adapter(live_route, scenario, tmp_path, record_property):
    provider, model, client, consume, key = live_route
    trace = run_case(provider, model, scenario, client, tmp_path, consume_request=consume)
    issues = grade(trace, scenario)
    record_property("provider", provider)
    record_property("model", model)
    record_property("scenario", scenario.id)
    record_property("request_count", len(trace.requests))
    record_property("failure_categories", ",".join(sorted({item["category"] for item in issues})))
    # Optional reports contain only synthetic prompts, tool data and provider output.
    # Never store client objects, headers, credentials, raw exceptions, or personal context.
    report_dir = os.getenv("OPENWAND_ADAPTER_REPORT_DIR", "").strip()
    if report_dir:
        target = Path(report_dir)
        target.mkdir(parents=True, exist_ok=True)
        report = json.dumps({**trace.to_dict(), "issues": issues}, ensure_ascii=False, indent=2)
        report = report.replace(key, "[REDACTED]")
        (target / f"{provider}--{scenario.id}.json").write_text(report + "\n", encoding="utf-8")
    assert not issues, json.dumps(issues, ensure_ascii=False)
