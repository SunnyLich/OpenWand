"""No-network tests of the explicitly authorized remaining-case scope."""

import copy
import json
from datetime import date
from pathlib import Path

import pytest

from .budget import Budget, GuardAbort
from .run_live import prepare_single_add


def prefix():
    return json.loads(Path(__file__).with_name("fixtures").joinpath("authorized-prefix.json").read_text())


def ledger():
    return Budget(today=date(2026, 10, 11))


def test_targeted_scope_preserves_all_prior_counters_and_failures():
    p, b = prefix(), ledger()
    plans, retained, superseded = prepare_single_add(p, b, p["limits"])
    assert [(s.name, mode) for s, mode in plans] == [("single_add", "tool_loop")]
    assert b.summary()["generation_requests"] == b.count_requests == 16
    assert b.reserved == 57363
    assert b.summary()["estimated_cost_usd"] == 0.013263
    assert b.records == p["usage"]["records"]
    assert [c["scenario"] for c in retained if c["status"] == "failed"] == ["json_arguments", "multiple_tools"]
    assert superseded[0]["request_numbers"] == [3]
    assert sorted(n for c in retained + superseded for n in c["request_numbers"]) == list(range(1, 17))


def test_targeted_run_stops_after_two_new_generations():
    p, b = prefix(), ledger()
    prepare_single_add(p, b, p["limits"])
    assert b.reserve(100, 100, 256)["request"] == 17
    assert b.reserve(100, 100, 256)["request"] == 18
    reserved = b.reserved
    with pytest.raises(GuardAbort):
        b.reserve(100, 100, 256)
    assert b.reserved == reserved and b.reserved > 57363


@pytest.mark.parametrize(
    "field,value",
    [("generation_requests", 0), ("count_tokens_requests", 0), ("reserved_usd", 0), ("estimated_cost_usd", 0)],
)
def test_targeted_scope_rejects_counter_reset(field, value):
    p = prefix()
    p["usage"][field] = value
    b = ledger()
    with pytest.raises(GuardAbort):
        prepare_single_add(p, b, p["limits"])
    assert not b.records


@pytest.mark.parametrize("status", ["passed", "failed", "skipped"])
def test_targeted_scope_cannot_repeat_other_statuses(status):
    p = prefix()
    p["cases"][2]["status"] = status
    with pytest.raises(GuardAbort):
        prepare_single_add(p, ledger(), p["limits"])


@pytest.mark.parametrize("change", ["abort", "uncertain_usage", "modified_reservation", "modified_total"])
def test_restoration_fails_closed_on_unsafe_prior_state(change):
    usage = copy.deepcopy(prefix()["usage"])
    if change == "abort":
        usage["abort"] = {"http_status": 500}
    elif change == "uncertain_usage":
        usage["usage_complete"] = False
    elif change == "modified_reservation":
        usage["records"][0]["reserved_micro_usd"] = 1
    else:
        usage["estimated_cost_usd"] = 0
    with pytest.raises(GuardAbort):
        ledger().restore_successful_ledger(usage)


def test_existing_budget_cannot_be_reset_by_restore():
    b = ledger()
    b.reserve(100, 100, 256)
    with pytest.raises(GuardAbort):
        b.restore_successful_ledger(prefix()["usage"])
