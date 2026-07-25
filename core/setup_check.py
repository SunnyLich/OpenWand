"""Lightweight setup checks safe to run from the Settings UI."""
from __future__ import annotations

from typing import Any

from core.error_recommendations import recommendation_for


def _status(ok: bool, warning: bool = False) -> str:
    if ok:
        return "pass"
    return "warn" if warning else "fail"


def _secret_for_provider(config: Any, provider: str) -> str:
    mapping = {
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "mistral": "MISTRAL_API_KEY",
        "xai": "XAI_API_KEY",
        "together": "TOGETHER_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
        "zai": "ZAI_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "sambanova": "SAMBANOVA_API_KEY",
        "github_models": "GITHUB_MODELS_API_KEY",
        "huggingface": "HUGGINGFACE_API_KEY",
        "chutes": "CHUTES_API_KEY",
        "vercel": "VERCEL_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
        "cohere": "COHERE_API_KEY",
        "ai21": "AI21_API_KEY",
        "nebius": "NEBIUS_API_KEY",
        "custom": "CUSTOM_API_KEY",
    }
    key_name = mapping.get(provider.lower(), "")
    return str(getattr(config, key_name, "") or "") if key_name else ""


def run_setup_check() -> list[dict[str, str]]:
    """Return setup check rows without importing audio, STT, or provider SDKs."""
    import config

    config.reload()
    rows: list[dict[str, str]] = []

    provider = str(getattr(config, "LLM_PROVIDER", "") or "").strip()
    model = str(getattr(config, "LLM_MODEL", "") or "").strip()
    llm_ok = bool(provider and model and (_secret_for_provider(config, provider) or provider in {"copilot", "chatgpt", "ollama"}))
    llm_message = (
        f"LLM route configured: {provider}/{model}."
        if llm_ok
        else f"LLM route incomplete: {provider or 'missing provider'}/{model or 'missing model'}."
    )
    rows.append(
        {
            "name": "LLM provider",
            "status": _status(llm_ok),
            "message": llm_message,
            "recommendation": "" if llm_ok else recommendation_for("missing API key"),
        }
    )

    from core import speech_status

    speech = speech_status.speech_status(config, verify_runtime=True)
    tts = dict(speech["tts"])
    tts_disabled = tts.get("state") == "disabled"
    tts_ok = bool(tts.get("usable")) or tts_disabled
    tts_recommendation = str(tts.get("action") or "")
    if tts_recommendation:
        tts_recommendation = f"Recommendation: {tts_recommendation}"
    rows.append(
        {
            "name": "TTS",
            "status": _status(tts_ok, warning=tts_disabled),
            "message": str(tts.get("summary") or "TTS status is unavailable."),
            "recommendation": "" if tts_ok else (tts_recommendation or recommendation_for("tts no audio")),
        }
    )

    stt = dict(speech["stt"])
    stt_model = str(stt.get("model") or "")
    stt_package_ok = bool(stt.get("usable"))
    stt_recommendation = str(stt.get("action") or "")
    if stt_recommendation:
        stt_recommendation = f"Recommendation: {stt_recommendation}"
    rows.append(
        {
            "name": "Speech to text",
            "status": "pass" if not stt_model else _status(stt_package_ok),
            "message": str(stt.get("summary") or "STT status is unavailable."),
            "recommendation": (
                ""
                if not stt_model or stt_package_ok
                else stt_recommendation
            ),
        }
    )

    hotkeys = [
        str(getattr(config, "HOTKEY_SNIP", "") or ""),
        str(getattr(config, "HOTKEY_SNIP_2", "") or ""),
        str(getattr(config, "HOTKEY_VOICE", "") or ""),
        str(getattr(config, "HOTKEY_VOICE_2", "") or ""),
        str(getattr(config, "HOTKEY_ADD_CONTEXT", "") or ""),
        str(getattr(config, "HOTKEY_ADD_CONTEXT_2", "") or ""),
    ]
    caller_rows = getattr(config, "CALLER_ROWS", []) or []
    for row in caller_rows:
        if not isinstance(row, dict) or not bool(row.get("enabled", True)):
            continue
        hotkeys.extend((str(row.get("hotkey") or ""), str(row.get("hotkey_2") or "")))
    enabled_hotkeys = [key for key in hotkeys if key.strip()]
    rows.append(
        {
            "name": "Hotkeys",
            "status": _status(bool(enabled_hotkeys)),
            "message": f"{len(enabled_hotkeys)} hotkeys configured.",
            "recommendation": "" if enabled_hotkeys else recommendation_for("hotkey conflict"),
        }
    )
    return rows
