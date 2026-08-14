"""Lightweight prompt-injection detection for captured text context."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any


class PromptInjectionReviewCanceled(RuntimeError):
    """The user canceled a send after a possible prompt injection was found."""


# A trigger only counts when an instruction-like noun appears among its next
# five words. This deliberately favors a small, explainable rule over broad
# keyword blocking that would flag ordinary uses of words such as "ignore".
_PROMPT_INJECTION_PATTERN = re.compile(
    r"\b(?P<trigger>"
    r"ignor(?:e|ed|es|ing)|"
    r"disregard(?:ed|s|ing)?|"
    r"forget(?:s|ting)?|"
    r"overrid(?:e|es|den|ing)|"
    r"bypass(?:ed|es|ing)?|"
    r"discard(?:ed|s|ing)?"
    r")\b"
    r"(?=(?:[^\w]+[\w'-]+){0,4}[^\w]+(?P<instruction>"
    r"instructions?|prompts?|directives?|rules?|commands?|"
    r"polic(?:y|ies)|guidance|guardrails?"
    r")\b)",
    re.IGNORECASE,
)


def detection_enabled() -> bool:
    """Return whether lightweight prompt-injection detection is enabled."""
    try:
        import config

        return bool(getattr(config, "PROMPT_INJECTION_PROTECTION", True))
    except Exception:
        return True


def warning_enabled() -> bool:
    """Return whether detections should pause for a local warning."""
    try:
        import config

        return bool(getattr(config, "PROMPT_INJECTION_WARN", True))
    except Exception:
        return True


def _local_preview(text: str, start: int, end: int, radius: int = 70) -> str:
    """Return a compact, single-line local preview around one match."""
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    preview = " ".join(text[left:right].split())
    if left:
        preview = "..." + preview
    if right < len(text):
        preview += "..."
    return preview


def detect_prompt_injections(fields: Mapping[str, object]) -> dict[str, Any]:
    """Detect simple override phrases in named, untrusted text fields."""
    items: list[dict[str, Any]] = []
    sources: dict[str, int] = {}
    for source, raw in fields.items():
        text = str(raw or "")
        for match in _PROMPT_INJECTION_PATTERN.finditer(text):
            _, instruction_end = match.span("instruction")
            item = {
                "source": str(source),
                "trigger": match.group("trigger"),
                "instruction": match.group("instruction"),
                "start": match.start(),
                "end": instruction_end,
                "preview": _local_preview(text, match.start(), instruction_end),
            }
            items.append(item)
            sources[str(source)] = sources.get(str(source), 0) + 1
    return {
        "count": len(items),
        "items": items,
        "sources": sources,
        "detector": "five-word-rule",
    }


def inspect_captured_text(
    fields: Mapping[str, object],
    *,
    review: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Inspect captured text and optionally require confirmation before send."""
    if not detection_enabled():
        return {"count": 0, "items": [], "sources": {}, "enabled": False}

    report = detect_prompt_injections(fields)
    report["enabled"] = True
    report["warning_enabled"] = warning_enabled()
    if not report["count"] or not report["warning_enabled"] or review is None:
        return report

    preview = "\n\n".join(
        f"[{source}]\n{str(value or '')}" for source, value in fields.items() if value
    )
    payload = dict(report)
    payload.update(
        {
            "review_kind": "prompt_injection",
            "scrubbed_preview": preview,
        }
    )
    result = review(payload)
    decision = str(result or "cancel").strip().lower()
    if decision not in {"full", "continue"}:
        raise PromptInjectionReviewCanceled(
            "Possible prompt injection detected. The request was canceled before sending."
        )
    report["reviewed"] = True
    report["decision"] = "continue"
    return report
