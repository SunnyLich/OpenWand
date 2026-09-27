"""Route failover + circuit breaker for LLM providers.

A small registry that prefers healthy fallbacks after temporary failures.
Only a provider rate limit blocks another user request; empty responses and
server errors remain retryable when no healthy fallback is available.
Split out of core.llm_clients.client; the names are re-exported there so the
module-level cooldown state stays a single shared object.
"""
from __future__ import annotations

import math
import re
import threading as _threading
import time as _time
from email.utils import parsedate_to_datetime

# Temporary failures prefer healthy fallbacks for this window, without
# blocking the user's only route. Rate limits use the provider's retry timing.
_ROUTE_COOLDOWN_SECONDS = 300.0

_route_cooldowns: dict[tuple[str, str], float] = {}

_route_cooldowns_lock = _threading.Lock()
_route_cooldown_details: dict[tuple[str, str], tuple[bool, str]] = {}

def _route_key(provider: str, model: str) -> tuple[str, str]:
    """Handle route key for LLM clients client."""
    return ((provider or "").lower(), model or "")

def _is_route_cooling(provider: str, model: str) -> bool:
    """Return whether route cooling is true."""
    key = _route_key(provider, model)
    with _route_cooldowns_lock:
        until = _route_cooldowns.get(key)
        if until is None:
            return False
        if _time.time() >= until:
            _route_cooldowns.pop(key, None)
            _route_cooldown_details.pop(key, None)
            return False
        return True

def _mark_route_cooling(provider: str, model: str, seconds: float = _ROUTE_COOLDOWN_SECONDS,
                        *, hard: bool = False, reason: str = "") -> None:
    """Prefer healthy fallbacks; only explicit rate limits block a manual retry."""
    with _route_cooldowns_lock:
        key = _route_key(provider, model)
        _route_cooldowns[key] = _time.time() + seconds
        _route_cooldown_details[key] = (hard, reason)


def _route_rate_limit_message(provider: str, model: str) -> str:
    """Include the original failure and remaining wait for an active rate limit."""
    with _route_cooldowns_lock:
        key = _route_key(provider, model)
        remaining = _route_cooldowns.get(key, 0) - _time.time()
        hard, reason = _route_cooldown_details.get(key, (False, ""))
    if remaining <= 0 or not hard:
        return ""
    return (
        f"{provider}/{model}: the provider reported a rate limit. "
        f"Retry in {math.ceil(remaining)} seconds. Original error: {reason}"
    )


def _clear_route_cooling(provider: str, model: str) -> None:
    with _route_cooldowns_lock:
        key = _route_key(provider, model)
        _route_cooldowns.pop(key, None)
        _route_cooldown_details.pop(key, None)


def _error_status(exc: Exception) -> int | None:
    """Read structured status first, including wrapped urllib errors."""
    for source in (exc, getattr(exc, "response", None), exc.__cause__):
        for name in ("status_code", "status", "code"):
            value = getattr(source, name, None)
            if str(value).isdigit() and 100 <= int(value) <= 599:
                return int(value)
    match = re.search(r"(?:HTTP(?: status)?|status(?: code)?|error code)[: =]*(\d{3})\b", str(exc), re.I)
    return int(match[1]) if match else None


def _is_quota_error(exc: Exception) -> bool:
    status = _error_status(exc)
    if status is not None:
        return status == 429
    name = type(exc).__name__.lower()
    return "ratelimit" in name or bool(re.search(
        r"\brate[ _-]?limit(?:ed|ing|s)?\b|\bquota (?:exceeded|exhausted)\b|\bRESOURCE_EXHAUSTED\b|\busage_limit_reached\b",
        str(exc), re.I,
    ))


def _is_transient_route_error(exc: Exception) -> bool:
    status = _error_status(exc)
    if status is not None:
        return status in {429, 500, 502, 503, 504}
    return _is_quota_error(exc) or bool(re.search(
        r"\b(?:service unavailable|temporarily unavailable|high demand|try again later)\b", str(exc), re.I,
    ))


def _provider_retry_seconds(exc: Exception) -> float:
    """Honor provider Retry-After; use a short wait when no duration is given."""
    for source in (exc, getattr(exc, "response", None), exc.__cause__):
        headers = getattr(source, "headers", None)
        if headers is None:
            continue
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw is None:
            continue
        try:
            seconds = float(raw)
        except (ValueError, TypeError):
            try:
                seconds = parsedate_to_datetime(str(raw)).timestamp() - _time.time()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(seconds):
            return max(1.0, seconds)
    # Google may put its retry duration in the error body instead of a header.
    match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', str(exc))
    if match:
        return max(1.0, float(match[1]))
    return 30.0


def _route_failure_summary(
    kind: str,
    attempts: list[tuple[str, str, Exception | str]],
    last_exc: Exception,
) -> RuntimeError:
    """Handle route failure summary for LLM clients client."""
    details = []
    for provider, model, err in attempts:
        details.append(f"{provider}/{model}: {err}")
    joined = "; ".join(details)
    return RuntimeError(f"All {kind} model routes failed. Tried {joined}")
