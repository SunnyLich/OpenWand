"""Cloudflare Workers AI speech-to-text client.

The microphone pipeline captures normalized float32 mono PCM.  This module keeps
the provider boundary small: encode that PCM as a standard WAV, submit it to
Cloudflare's Workers AI REST endpoint, and return only the transcript text.
"""
from __future__ import annotations

import base64
import io
import math
import wave
from collections.abc import Callable
from typing import Any

import numpy as np

DEFAULT_MODEL = "@cf/openai/whisper-large-v3-turbo"
API_ROOT = "https://api.cloudflare.com/client/v4/accounts"


class CloudflareSTTError(RuntimeError):
    """Raised when Cloudflare cannot complete a transcription request."""


class CloudflareSTTConfigurationError(CloudflareSTTError):
    """Raised when required Cloudflare credentials are missing."""


def _wav_base64(audio: np.ndarray, sample_rate: int) -> str:
    """Encode mono float PCM as a base64 WAV accepted by Workers AI."""
    samples = np.asarray(audio, dtype="float32").reshape(-1)
    samples = np.nan_to_num(samples, nan=0.0, posinf=1.0, neginf=-1.0)
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm)
    return base64.b64encode(out.getvalue()).decode("ascii")


def _error_detail(response: Any) -> str:
    """Extract a useful provider error without ever including credentials."""
    try:
        body = response.json()
    except Exception:
        body = None
    if isinstance(body, dict):
        errors = body.get("errors")
        if isinstance(errors, list):
            messages = [
                str(item.get("message") or item.get("code") or "").strip()
                for item in errors
                if isinstance(item, dict)
            ]
            detail = "; ".join(message for message in messages if message)
            if detail:
                return detail
        for key in ("error", "message"):
            detail = str(body.get(key) or "").strip()
            if detail:
                return detail
    return str(getattr(response, "reason", "") or "request failed").strip()


def transcribe(
    audio: np.ndarray,
    *,
    account_id: str,
    api_token: str,
    sample_rate: int = 16_000,
    language: str | None = None,
    beam_size: int = 5,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 90.0,
    post: Callable[..., Any] | None = None,
) -> str:
    """Transcribe one mono PCM buffer using Cloudflare Workers AI."""
    account_id = str(account_id or "").strip()
    api_token = str(api_token or "").strip()
    model = str(model or DEFAULT_MODEL).strip()
    if not account_id:
        raise CloudflareSTTConfigurationError("Cloudflare Account ID is not configured.")
    if not api_token:
        raise CloudflareSTTConfigurationError("Cloudflare Workers AI API token is not configured.")
    if not model.startswith("@cf/"):
        raise CloudflareSTTConfigurationError("Cloudflare STT model must start with '@cf/'.")
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")

    samples = np.asarray(audio, dtype="float32").reshape(-1)
    if not samples.size:
        return ""
    if post is None:
        import requests

        post = requests.post

    payload: dict[str, Any] = {
        "audio": _wav_base64(samples, sample_rate),
        "task": "transcribe",
        "vad_filter": True,
        "beam_size": max(1, min(int(beam_size), 10)),
        # Each OpenWand background window already overlaps its neighbor. Avoid
        # conditioning separate API requests on text they cannot share.
        "condition_on_previous_text": False,
    }
    if language:
        payload["language"] = str(language).strip()

    timeout = float(timeout_seconds)
    if not math.isfinite(timeout):
        timeout = 90.0
    timeout = max(5.0, min(timeout, 300.0))
    url = f"{API_ROOT}/{account_id}/ai/run/{model}"
    try:
        response = post(
            url,
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except Exception as exc:
        raise CloudflareSTTError(
            f"Cloudflare STT request failed: {type(exc).__name__}: {exc}"
        ) from exc

    status = int(getattr(response, "status_code", 0) or 0)
    if status >= 400:
        detail = _error_detail(response)
        if status == 401 or status == 403:
            raise CloudflareSTTError(
                f"Cloudflare rejected the STT credentials ({status}): {detail}"
            )
        if status == 429:
            raise CloudflareSTTError(
                f"Cloudflare STT quota or rate limit was reached (429): {detail}"
            )
        raise CloudflareSTTError(f"Cloudflare STT returned HTTP {status}: {detail}")

    try:
        body = response.json()
    except Exception as exc:
        raise CloudflareSTTError("Cloudflare STT returned invalid JSON.") from exc
    if not isinstance(body, dict):
        raise CloudflareSTTError("Cloudflare STT returned an unexpected response.")
    if body.get("success") is False:
        raise CloudflareSTTError(f"Cloudflare STT failed: {_error_detail(response)}")
    result = body.get("result", body)
    if not isinstance(result, dict):
        raise CloudflareSTTError("Cloudflare STT response did not contain a result object.")
    text = result.get("text")
    if text is None and isinstance(result.get("transcription_info"), dict):
        text = result["transcription_info"].get("text")
    if text is None:
        raise CloudflareSTTError("Cloudflare STT response did not contain transcript text.")
    return str(text).strip()


def test_connection(
    *,
    account_id: str,
    api_token: str,
    model: str = DEFAULT_MODEL,
    timeout_seconds: float = 30.0,
    post: Callable[..., Any] | None = None,
) -> tuple[bool, str]:
    """Run a tiny silent inference to verify credentials and model access."""
    try:
        text = transcribe(
            np.zeros(8_000, dtype="float32"),
            account_id=account_id,
            api_token=api_token,
            sample_rate=16_000,
            language="en",
            beam_size=1,
            model=model,
            timeout_seconds=timeout_seconds,
            post=post,
        )
    except Exception as exc:  # noqa: BLE001 - returned as a user-facing test result
        return False, str(exc)
    suffix = f" Transcript: {text}" if text else ""
    return True, f"Cloudflare Workers AI STT is reachable.{suffix}"
