"""Preserve provider error fields across worker boundaries without SDK objects."""

from __future__ import annotations

import math
import re
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

_PRIVATE_FIELDS = {
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "id_token",
    "idtoken",
    "password",
    "secret",
    "client_secret",
    "clientsecret",
    "token",
    "credential",
}
_REQUEST_FIELDS = {"request", "headers", "input", "prompt", "messages"}


def redact(text: str, secrets=()) -> str:
    for secret in secrets:
        if isinstance(secret, str) and len(secret) >= 8:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s\"',}]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{8,}|gsk_[A-Za-z0-9_-]{8,}|AIza[A-Za-z0-9_-]{20,})", "[REDACTED]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)
    return re.sub(
        r"""(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)["']?\s*[:=]\s*["']?)([^\s"',}&]+)""",
        r"\1[REDACTED]",
        text,
    )


def _safe(value, secrets=(), depth=0):
    if depth > 12:
        return "[Nested details omitted]"
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]"
            if str(k).lower().replace("-", "_") in _PRIVATE_FIELDS
            else _safe(v, secrets, depth + 1)
            for k, v in value.items()
            if str(k).lower() not in _REQUEST_FIELDS
        }
    if isinstance(value, list):
        return [_safe(v, secrets, depth + 1) for v in value[:100]]
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value if value is None or isinstance(value, (int, float, bool)) else redact(str(value), secrets)


def _error_object(body):
    if isinstance(body, list):
        return next((item.get("error", item) for item in body if isinstance(item, dict)), {})
    if isinstance(body, dict):
        error = body.get("error", body)
        return error if isinstance(error, dict) else {"message": str(error)}
    return {}


def _retry_seconds(exc, error):
    for source in (exc, getattr(exc, "response", None)):
        headers = getattr(source, "headers", None)
        if headers is None:
            continue
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw is not None:
            try:
                seconds = float(raw)
            except (ValueError, TypeError):
                try:
                    seconds = parsedate_to_datetime(str(raw)).timestamp() - datetime.now(UTC).timestamp()
                except (ValueError, TypeError, OverflowError):
                    continue
            if math.isfinite(seconds):
                return max(0, seconds)
    details = error.get("details", [])
    if not isinstance(details, list):
        details = [details] if isinstance(details, dict) else []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        raw = detail.get("retryDelay")
        if isinstance(raw, str) and re.fullmatch(r"\d+(?:\.\d+)?s", raw):
            return float(raw[:-1])
    return None


def from_exception(exc: Exception, *, provider="", model="", secrets=()) -> dict:
    existing = getattr(exc, "provider_error", None)
    if isinstance(existing, dict) and existing.get("message"):
        return _safe(deepcopy(existing), secrets)
    body = getattr(exc, "body", None)
    if body is None:
        response = getattr(exc, "response", None)
        try:
            body = response.json() if response is not None else None
        except (ValueError, RuntimeError, AttributeError):
            pass
    error = _error_object(body)
    # Attribute HTTP errors using structured fields, never numbers guessed
    # from exception wording that might describe an entirely local failure.
    status = None
    for source in (exc, getattr(exc, "response", None), exc.__cause__):
        for key in ("status_code", "status", "code"):
            value = getattr(source, key, None)
            if isinstance(value, (int, str)) and str(value).isdigit() and 100 <= int(value) <= 599:
                status = int(value)
                break
        if status is not None:
            break
    message = error.get("message")
    if not isinstance(message, str) or not message.strip():
        message = str(exc) or type(exc).__name__
    code = error.get("status") or error.get("code") or error.get("type") or ""
    if isinstance(code, (dict, list)):
        code = ""
    info = {
        "provider": provider,
        "model": model,
        "http_status": status,
        "code": str(code),
        "source": "provider" if status is not None else "openwand",
        "message": message,
        "diagnostics": {"exception_type": type(exc).__name__, "provider_response": error},
    }
    retry = _retry_seconds(exc, error)
    if retry is not None:
        info["retry_after_seconds"] = retry
        info["retry_source"] = "provider"
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str):
        info["request_id"] = request_id
    if exc.__traceback__:
        info["diagnostics"]["traceback"] = "".join(traceback.format_tb(exc.__traceback__))
    return _safe(info, secrets)


def normalize(info) -> dict:
    if not isinstance(info, dict) or not isinstance(info.get("message"), str):
        return from_exception(RuntimeError(str(info or "Unknown error")))
    return _safe(deepcopy(info))


def from_provider_event(error, *, provider: str, model: str) -> dict:
    """An API stream can report an error after its HTTP 200 handshake."""
    if not isinstance(error, dict):
        error = {
            key: getattr(error, key)
            for key in ("message", "code", "type", "param", "details")
            if getattr(error, key, None) is not None
        }
    exc = RuntimeError(str(error.get("message") or "Provider returned an error event"))
    exc.body = {"error": error}
    info = from_exception(exc, provider=provider, model=model)
    info["source"] = "provider"
    return info
