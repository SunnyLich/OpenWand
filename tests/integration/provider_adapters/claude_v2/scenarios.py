"""Shared synthetic prompts, tool schemas, expected calls and local execution."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

SYSTEM = "Follow the request precisely. Use only the supplied synthetic tools when asked. Keep the final answer short."


def tool(name, description, properties, required):
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = {
    "qa_add": tool(
        "qa_add",
        "Add two integers.",
        {"a": {"type": "integer"}, "b": {"type": "integer"}},
        ["a", "b"],
    ),
    "qa_upper": tool("qa_upper", "Uppercase the given text.", {"text": {"type": "string"}}, ["text"]),
    "qa_record": tool(
        "qa_record",
        "Echo a structured record unchanged.",
        {"payload": {"type": "object"}},
        ["payload"],
    ),
    "qa_lookup": tool(
        "qa_lookup",
        "Look up a synthetic code. Returns token and value, or a synthetic error.",
        {"code": {"type": "string"}},
        ["code"],
    ),
}
NESTED = {
    "label": 'caf\u00e9 "blue"',
    "items": [1, True, None],
    "meta": {"active": False},
}


@dataclass(frozen=True)
class Scenario:
    name: str
    prompt: str
    offered: tuple
    rounds: tuple
    expected_text: str


SCENARIOS = (
    Scenario("no_tools", "Reply with exactly QA_OK.", (), (), "QA_OK"),
    Scenario(
        "single_add",
        "Call qa_add with a=2 and b=3. After its result, reply with exactly 5.",
        ("qa_add",),
        ((("qa_add", {"a": 2, "b": 3}),),),
        "5",
    ),
    Scenario(
        "distinct_selection",
        "Use qa_upper, not qa_add, to uppercase orchid. Reply with exactly the returned text.",
        ("qa_add", "qa_upper"),
        ((("qa_upper", {"text": "orchid"}),),),
        "ORCHID",
    ),
    Scenario(
        "json_arguments",
        "Call qa_record once with payload equal to "
        + json.dumps(NESTED, ensure_ascii=False)
        + ". Then reply with exactly RECORDED.",
        ("qa_record",),
        ((("qa_record", {"payload": NESTED}),),),
        "RECORDED",
    ),
    Scenario(
        "result_round_trip",
        "Call qa_lookup with code=alpha. Reply with exactly the token returned by the tool; do not guess it.",
        ("qa_lookup",),
        ((("qa_lookup", {"code": "alpha"}),),),
        "LILAC_83",
    ),
    Scenario(
        "multiple_tools",
        "In the same turn call qa_add(a=4,b=5) and qa_upper(text=iris). After both results, reply with exactly 9 IRIS.",
        ("qa_add", "qa_upper"),
        ((("qa_add", {"a": 4, "b": 5}), ("qa_upper", {"text": "iris"})),),
        "9 IRIS",
    ),
    Scenario(
        "multi_round",
        "First call qa_lookup(code=beta). After reading its result, call qa_add with a equal to its returned value and b=2. Finally reply with exactly the sum.",
        ("qa_lookup", "qa_add"),
        ((("qa_lookup", {"code": "beta"}),), (("qa_add", {"a": 7, "b": 2}),)),
        "9",
    ),
    Scenario(
        "tool_error",
        "Call qa_lookup(code=missing). If it fails, do not retry or call another tool. Reply with exactly SYNTHETIC_ERROR.",
        ("qa_lookup",),
        ((("qa_lookup", {"code": "missing"}),),),
        "SYNTHETIC_ERROR",
    ),
)


def schemas(scenario, family):
    items = [TOOLS[name] for name in scenario.offered]
    if family == "anthropic":
        return items
    functions = [
        {
            "type": "function",
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
        for t in items
    ]
    if family == "responses":
        return functions
    return [{"type": "function", "function": {k: v for k, v in t.items() if k != "type"}} for t in functions]


def execute(name, arguments):
    if name == "qa_add":
        return str(arguments["a"] + arguments["b"])
    if name == "qa_upper":
        return arguments["text"].upper()
    if name == "qa_record":
        return json.dumps(arguments["payload"], ensure_ascii=False)
    if name == "qa_lookup":
        return {
            "alpha": '{"token":"LILAC_83","value":11}',
            "beta": '{"token":"MOSS_24","value":7}',
        }.get(arguments["code"], "Synthetic lookup failed: not found")
    raise AssertionError("unoffered synthetic tool")


def expected_calls(scenario):
    return [call for calls in scenario.rounds for call in calls]


def grade(scenario, calls, final_text):
    """Original strict grader; retained unchanged for historical comparability."""
    expected = expected_calls(scenario)

    def canonical(entries):
        return sorted(json.dumps([name, args], sort_keys=True, ensure_ascii=False) for name, args in entries)

    problems = []
    if canonical(calls) != canonical(expected):
        problems.append("tool_names_or_json_arguments")
    if final_text.strip() != scenario.expected_text:
        problems.append("final_text")
    if scenario.name == "multi_round" and [name for name, _ in calls] != [
        "qa_lookup",
        "qa_add",
    ]:
        problems.append("tool_order")
    return problems


def grade_dimensions(scenario, calls, final_text, provider_rounds=None):
    """Separate tool semantics, answer content, and exact presentation.

    Ignore whitespace and punctuation between the same ordered word tokens;
    preserve case, numbers, identifiers and all additional/contradictory words.
    This narrow deterministic check does not pretend to grade arbitrary prose.
    It never relaxes tool names, argument types/values, order or round grouping.
    """
    exact = grade(scenario, calls, final_text)
    tool_problems = [p for p in exact if p != "final_text"]
    if scenario.name == "multiple_tools" and provider_rounds is not None:
        if not any(len(r) == 2 for r in provider_rounds):
            tool_problems.append("tools_not_in_same_turn")
    content_matches = re.findall(r"\w+", final_text) == re.findall(r"\w+", scenario.expected_text)
    return {
        "tool_contract": "passed" if not tool_problems else "failed",
        "tool_problems": tool_problems,
        "answer_content": "passed" if content_matches else "failed",
        "exact_output": "passed" if "final_text" not in exact else "failed",
        "exact_problems": exact,
    }
