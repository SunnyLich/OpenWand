"""Explicit one-shot Claude live QA; never run from pytest or import time.

Only the exact user-configured env name is read. No credential is written or
included in reports. No fallback provider or retries. O_EXCL marker prevents
accidental reruns with a fresh in-memory budget. Retain it with the results.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import io
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from .budget import (
    COUNTING_URL,
    MODEL,
    PRICE_DATE,
    PRICING_URL,
    Budget,
    GuardAbort,
    GuardedMessages,
)
from .scenarios import SCENARIOS, SYSTEM, execute, grade_dimensions, schemas


def unstarted_plans(report, plans):
    skipped = {(c["scenario"], c["mode"]) for c in report["cases"] if c["status"] == "skipped"}
    return [(s, mode) for s, mode in plans if (s.name, mode) in skipped]


def prepare_single_add(previous, budget, limits):
    """Narrow one-shot authorization: preserve the exact prior ledger, no other case."""
    if previous["model"] != MODEL or previous["limits"] != limits:
        raise GuardAbort("targeted run configuration mismatch")
    usage = previous["usage"]
    if (
        usage["generation_requests"],
        usage["count_tokens_requests"],
        usage["reserved_usd"],
        usage["estimated_cost_usd"],
    ) != (16, 16, 0.057363, 0.013263):
        raise GuardAbort("targeted run requires the authorized existing cumulative ledger")
    targets = [c for c in previous["cases"] if c["scenario"] == "single_add" and c["mode"] == "tool_loop"]
    if len(targets) != 1 or targets[0]["status"] != "blocked":
        raise GuardAbort("single-add target is not the remaining incomplete case")
    budget.restore_successful_ledger(usage)
    # One tool generation plus its final response; no further turn may be sent.
    budget.generation_limit = len(budget.records) + 2
    retained, superseded = [], []
    cursor = 0
    for original in previous["cases"]:
        case = copy.deepcopy(original)
        count = 1 if case["scenario"] == "single_add" else case["requests"]
        case["request_numbers"] = list(range(cursor + 1, cursor + count + 1))
        cursor += count
        if case["scenario"] == "single_add":
            superseded.append(case)
        else:
            retained.append(case)
    if cursor != len(budget.records):
        raise GuardAbort("case accounting does not cover prior ledger")
    return [(SCENARIOS[1], "tool_loop")], retained, superseded


def run(output, continue_unrun=False, complete_single_add=False):
    if continue_unrun and complete_single_add:
        raise GuardAbort("choose only one continuation scope")
    logging.disable(logging.CRITICAL)
    sys.path.insert(
        0,
        str(Path(os.environ.get("OPENWAND_CHECKOUT", str(Path(__file__).resolve().parents[4]))).resolve()),
    )
    import anthropic

    from core.llm_clients import client as llm
    from core.llm_clients.anthropic_chat_adapter import AnthropicChatLoopModel
    from core.llm_clients.chat_tool_loop import ChatToolRequest

    plans = [(SCENARIOS[0], "create"), (SCENARIOS[0], "stream")] + [(s, "tool_loop") for s in SCENARIOS[1:]]
    providers = json.loads(Path(__file__).with_name("providers.json").read_text())
    if (
        providers[0]["credential_env"] != "Anthropic_API_Key"
        or providers[0]["model"] != MODEL
        or any(p["live_enabled"] for p in providers[1:])
    ):
        raise GuardAbort("provider configuration exceeds authorized scope")
    b = Budget()
    report = {
        "suite_origin": "fresh implementation from checkout; inaccessible prior bundle not used",
        "started_utc": dt.datetime.now(dt.UTC).isoformat(),
        "model": MODEL,
        "pricing": {
            "verified_date": PRICE_DATE,
            "input_usd_per_million": 1,
            "output_usd_per_million": 5,
            "sources": [PRICING_URL, COUNTING_URL],
        },
        "limits": {
            "reservation_cap_usd": 0.20,
            "max_generation_requests": 36,
            "max_output_tokens": 256,
            "retries": 0,
            "fallback": False,
        },
        "cases": [],
        "provider_matrix": [],
    }
    for p in providers[1:]:
        report["provider_matrix"].append(
            {
                "provider": p["provider"],
                "status": "skipped",
                "reason": "live credentials, model and budget not configured in this suite",
                "offline_adapter_coverage": True,
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    if complete_single_add:
        previous_bytes = output.read_bytes()
        previous = json.loads(previous_bytes)
        plans, retained, superseded = prepare_single_add(previous, b, report["limits"])
        with (output.parent / "live-before-single-add.json").open("xb") as f:
            f.write(previous_bytes)
        report["cases"] = retained
        report["superseded_incomplete_attempts"] = superseded
        report["targeted_completion"] = {
            "authorized_scope": "single_add only; one fresh targeted case after local harness correction",
            "prior_generations": len(b.records),
            "prior_count_requests": b.count_requests,
            "prior_reserved_usd": b.reserved / 1_000_000,
            "prior_estimated_cost_usd": b.summary()["estimated_cost_usd"],
            "additional_generation_limit": 2,
            "provider_retries": 0,
            "preserved_previous_report": "live-before-single-add.json",
        }
    if continue_unrun:
        previous = json.loads(output.read_text())
        if previous["model"] != MODEL or previous["limits"] != report["limits"]:
            raise GuardAbort("continuation configuration mismatch")
        b.restore_completed_prefix(previous["usage"])
        plans = unstarted_plans(previous, plans)
        if not plans:
            raise GuardAbort("no unstarted scenarios")
        with (output.parent / "live-initial.json").open("x") as f:
            json.dump(previous, f, ensure_ascii=False, indent=2)
        report["cases"] = [c for c in previous["cases"] if c["status"] != "skipped"]
        report["continuation"] = {
            "initial_started_utc": previous["started_utc"],
            "prior_reservation_usd": b.reserved / 1_000_000,
            "prior_generations": len(b.records),
            "reason": "Guard omitted SDK direct-caller metadata; fixed and tested offline. Only unstarted scenarios continued; incomplete single_add was not retried.",
        }
    marker_name = (
        "live-single-add-started.json"
        if complete_single_add
        else ("live-continuation-started.json" if continue_unrun else "live-started.json")
    )
    marker = output.parent / marker_name
    with marker.open("x") as f:
        json.dump(
            {
                "started_utc": report["started_utc"],
                "model": MODEL,
                "reservation_cap_usd": 0.20,
            },
            f,
        )
    client = None
    abort = None
    try:
        if not os.environ.get("Anthropic_API_Key"):
            raise GuardAbort("exact Anthropic_API_Key missing or empty")
        client = anthropic.Anthropic(
            api_key=os.environ["Anthropic_API_Key"],
            base_url="https://api.anthropic.com",
            max_retries=0,
            timeout=25.0,
        )
        guarded = NS(messages=GuardedMessages(client.messages, b))
        for scenario, mode in plans:
            if abort:
                report["cases"].append(
                    {
                        "scenario": scenario.name,
                        "mode": mode,
                        "status": "skipped",
                        "classification": "infrastructure",
                        "reason": "run aborted; no retries",
                    }
                )
                continue
            start = len(b.records)
            executed = []

            def synthetic(name, arguments, scenario=scenario, executed=executed, **kwargs):
                if name not in scenario.offered:
                    raise GuardAbort("unoffered synthetic tool")
                executed.append((name, arguments))
                return execute(name, arguments)

            try:
                llm._route_capabilities.clear()
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.object(llm, "_execute_model_tool", synthetic))
                    stack.enter_context(patch.object(llm, "_log_context", lambda *a, **k: None))
                    stack.enter_context(patch.object(llm, "_log_offered_model_tools", lambda *a, **k: None))
                    stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    if mode == "create":
                        messages = [{"role": "user", "content": scenario.prompt}]
                        req = ChatToolRequest(
                            messages,
                            SYSTEM,
                            {"provider": "anthropic", "model": MODEL},
                            [],
                            [],
                            None,
                            {},
                            {},
                        )
                        adapter = AnthropicChatLoopModel(
                            guarded,
                            model=MODEL,
                            system=SYSTEM,
                            messages=messages,
                            tools=[],
                            max_tokens=256,
                        )
                        text = adapter.next_turn(req, [], []).final_text
                    elif mode == "stream":
                        text = llm._collect_answer_text(
                            llm._stream_anthropic(
                                scenario.prompt,
                                None,
                                MODEL,
                                guarded,
                                system_prompt=SYSTEM,
                                max_tokens=256,
                                use_tools=False,
                            )
                        )
                    else:
                        text = llm._collect_answer_text(
                            llm._run_unified_anthropic_tool_loop(
                                guarded,
                                model=MODEL,
                                system=SYSTEM,
                                messages=[{"role": "user", "content": scenario.prompt}],
                                tools=schemas(scenario, "anthropic"),
                                max_tokens=256,
                                allowed_tools=list(scenario.offered),
                                user_intent=scenario.prompt,
                                max_rounds=4,
                            )
                        )
                records = b.records[start:]
                raw_calls = [(c["name"], c["arguments"]) for r in records for c in r.get("provider_tool_calls", [])]
                rounds = [r.get("provider_tool_calls", []) for r in records]
                dimensions = grade_dimensions(scenario, executed, text, rounds)
                raw_dimensions = grade_dimensions(scenario, raw_calls, records[-1].get("provider_text", ""), rounds)
                problems = list(dimensions["tool_problems"])
                raw_problems = list(raw_dimensions["tool_problems"])
                if dimensions["answer_content"] == "failed":
                    problems.append("answer_content")
                if raw_dimensions["answer_content"] == "failed":
                    raw_problems.append("answer_content")
                truncated = any(r.get("stop_reason") == "max_tokens" for r in records)
                if truncated:
                    problems.append("generation_truncated")
                classification = "pass" if not problems else ("model" if raw_problems or truncated else "adapter")
                case = {
                    "scenario": scenario.name,
                    "mode": mode,
                    "status": "passed" if not problems else "failed",
                    "classification": classification,
                    "problems": problems,
                    "final_text": text,
                    "tool_calls": executed,
                    "requests": len(records),
                    "request_numbers": [r["request"] for r in records],
                    "grading_dimensions": dimensions,
                    "strict_status": "failed" if dimensions["exact_problems"] else "passed",
                }
            except Exception as exc:
                abort = {"error_class": type(exc).__name__, "details": b.abort_info}
                case = {
                    "scenario": scenario.name,
                    "mode": mode,
                    "status": "blocked",
                    "classification": "infrastructure",
                    "error": abort,
                }
            report["cases"].append(case)
            report["usage"] = b.summary()
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
            print(
                json.dumps({k: case[k] for k in ("scenario", "mode", "status", "classification")}),
                flush=True,
            )
    except Exception as exc:
        abort = {"error_class": type(exc).__name__, "details": b.abort_info}
    finally:
        if client:
            client.close()
        done = {(c["scenario"], c["mode"]) for c in report["cases"]}
        for s, mode in plans:
            if (s.name, mode) not in done:
                report["cases"].append(
                    {
                        "scenario": s.name,
                        "mode": mode,
                        "status": "skipped",
                        "classification": "infrastructure",
                        "reason": "run could not start",
                    }
                )
        report["usage"] = b.summary()
        report["abort"] = abort
        report["finished_utc"] = dt.datetime.now(dt.UTC).isoformat()
        incomplete = any(c["status"] in {"blocked", "skipped"} for c in report["cases"])
        report["provider_matrix"].insert(
            0,
            {
                "provider": "anthropic",
                "status": "partial" if incomplete else "completed",
            },
        )
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": str(output),
                "usage": {k: v for k, v in b.summary().items() if k != "records"},
                "abort": abort,
            }
        ),
        flush=True,
    )
    return 1 if abort or any(c["status"] == "failed" for c in report["cases"]) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live",
        action="store_true",
        required=True,
        help="spend authorized existing credit, at most $0.20 reservation",
    )
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results/live.json")
    parser.add_argument(
        "--continue-unrun",
        action="store_true",
        help="retain prior reservations and continue only never-started cases after the local SDK compatibility fix",
    )
    parser.add_argument(
        "--complete-single-add",
        action="store_true",
        help="authorized one-shot single-add completion, preserving all prior spend; at most two new generations",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(run(args.output, args.continue_unrun, args.complete_single_add))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_class": type(exc).__name__,
                    "detail": "pre-run guard failure; exception body withheld",
                }
            )
        )
        raise SystemExit(1) from None
