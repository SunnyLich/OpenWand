"""Optional rich-reply presentation addon for OpenWand."""

from __future__ import annotations

from typing import Any

from core.addon_manager import addon_setting

from .formatter_contract import (
    FormatContractError,
    assert_protected_tokens,
    builtin_formatted_html,
    formatting_prompt,
    repair_formatting_prompt,
    sanitize_formatted_html,
    verification_prompt,
)

ADDON_ID = "formatted-replies"


def _bool_setting(key: str, default: bool = False) -> bool:
    value = addon_setting(ADDON_ID, key, default)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _formatter_route() -> str:
    """Return the narrow, host-approved formatter model route."""
    method = str(
        addon_setting(ADDON_ID, "formatting_method", "Built-in renderer") or ""
    ).strip().lower()
    if method != "model-generated layout":
        return "builtin"
    value = str(addon_setting(ADDON_ID, "formatter_model", "") or "").strip().lower()
    routes = {
        "built-in renderer": "builtin",
        "local (ollama)": "ollama-local",
        "efficient (gpt-5.4-mini)": "chatgpt-mini",
        "fastest (gpt-5.4-nano)": "chatgpt-nano",
        "openwand llm model": "llm",
        "openwand chat model": "chat",
    }
    if value in routes:
        return routes[value]
    # Preserve the old route setting for anyone who already selected it. New
    # installs default to the cheaper mini model instead of the main GPT-5.5.
    legacy = str(addon_setting(ADDON_ID, "formatter_route", "") or "").strip().lower()
    if legacy == "chat route":
        return "chat"
    if legacy == "llm route":
        return "llm"
    return "chat"


def _local_formatter_model() -> str:
    """Return an optional explicit Ollama model; blank means first installed."""
    return str(addon_setting(ADDON_ID, "formatter_local_model", "") or "").strip()


def _formatter_model_details(route: str | None = None) -> tuple[str, str]:
    """Resolve the provider and exact model the next formatting call will use."""
    import config

    selected_route = route or _formatter_route()
    if selected_route == "builtin":
        return "openwand", "built-in renderer"
    if selected_route == "chatgpt-mini":
        return "chatgpt", "gpt-5.4-mini"
    if selected_route == "chatgpt-nano":
        return "chatgpt", "gpt-5.4-nano"
    if selected_route == "chat":
        return (
            str(config.CHAT_LLM_PROVIDER or "").strip(),
            str(config.CHAT_LLM_MODEL or "").strip(),
        )
    if selected_route == "llm":
        return (
            str(config.LLM_PROVIDER or "").strip(),
            str(config.LLM_MODEL or "").strip(),
        )
    model = _local_formatter_model()
    if not model:
        try:
            from core.llm_clients import client as llm_client

            models, _error = llm_client.safe_list_models("ollama")
            model = str(models[0] if models else "").strip()
        except Exception:
            model = ""
    return "ollama", model


def get_message_actions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Expose a single restrained action on assistant messages."""
    role = str((payload or {}).get("role") or "assistant").strip().lower()
    if role not in {"assistant", "all"}:
        return []
    route = _formatter_route()
    provider, model = _formatter_model_details(route)
    return [{
        "id": "format-reply",
        "label": "Format",
        "role": "assistant",
        "presentation": True,
        "auto": _bool_setting("auto_format", True),
        "provider": provider,
        "model": model,
    }]


def get_settings() -> list[dict[str, Any]]:
    """Settings are declared in addon.toml; no dynamic rows are needed."""
    return []


def run_message_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Ask OpenWand's bounded addon-LLM service for a presentation fragment."""
    if action_id != "format-reply":
        return {"status": "Unknown formatted-reply action. Original kept."}
    canonical = str((payload or {}).get("text") or "")
    if not canonical.strip():
        return {"status": "Nothing to format. Original kept."}
    preference = str(addon_setting(ADDON_ID, "presentation_preference", "") or "")
    prompt = formatting_prompt(
        str((payload or {}).get("user_prompt") or ""),
        canonical,
        preference,
    )
    route = _formatter_route()
    provider, model = _formatter_model_details(route)
    if route == "builtin":
        state = {
            "canonical": canonical,
            "route": route,
            "model": model,
            "provider": provider,
        }
        try:
            return _presentation(builtin_formatted_html(canonical), state, "Formatted")
        except FormatContractError as exc:
            return {
                "status": "Formatting failed. Original kept. Exact content could not be preserved.",
                "error_detail": str(exc),
            }
    return {
        "status": "Formatting…",
        "llm": {
            "prompt": prompt,
            "max_tokens": 4096,
            "temperature": 0.25,
            "route": route,
            "model": model,
        },
        "state": {
            "phase": "format",
            "canonical": canonical,
            "verify": _bool_setting("verify_meaning", False),
            "route": route,
            "model": model,
            "provider": provider,
        },
    }


def _presentation(fragment: str, state: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "status": status,
        "model": str(state.get("used_model") or state.get("model") or ""),
        "provider": str(state.get("used_provider") or state.get("provider") or ""),
        "presentation": {
            "format": "restricted_html",
            "html": fragment,
            "label": "Formatted",
            "status": status,
        },
        "token_usage": {
            "formatting_input_estimate": int(state.get("formatting_input_estimate") or 0),
            "formatting_output_estimate": int(state.get("formatting_output_estimate") or 0),
            "verification_input_estimate": int(state.get("verification_input_estimate") or 0),
            "verification_output_estimate": int(state.get("verification_output_estimate") or 0),
        },
    }


def resume_message_action(action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate formatting output, and optionally ask for a meaning check."""
    if action_id != "format-reply":
        return {"status": "Unknown formatted-reply action. Original kept."}
    state = dict((payload or {}).get("state") or {})
    used_model = str((payload or {}).get("model") or "").strip()
    used_provider = str((payload or {}).get("provider") or "").strip()
    if used_model:
        state["used_model"] = used_model
        state["model"] = used_model
    if used_provider:
        state["used_provider"] = used_provider
        state["provider"] = used_provider
    phase = str(state.get("phase") or "format")
    llm_text = str((payload or {}).get("text") or "")
    try:
        if phase == "format":
            canonical = str(state.get("canonical") or "")
            state["formatting_input_estimate"] = (
                int(state.get("formatting_input_estimate") or 0)
                + int((payload or {}).get("input_tokens_estimate") or 0)
            )
            state["formatting_output_estimate"] = (
                int(state.get("formatting_output_estimate") or 0)
                + int((payload or {}).get("output_tokens_estimate") or 0)
            )
            try:
                fragment = sanitize_formatted_html(llm_text)
                assert_protected_tokens(canonical, fragment)
            except FormatContractError as exc:
                if int(state.get("format_retry") or 0) < 1:
                    state["format_retry"] = 1
                    preference = str(addon_setting(ADDON_ID, "presentation_preference", "") or "")
                    return {
                        "status": "Repairing format…",
                        "llm": {
                            "prompt": repair_formatting_prompt(
                                canonical,
                                llm_text,
                                str(exc),
                                preference,
                            ),
                            "max_tokens": 4096,
                            "temperature": 0.1,
                            "route": str(state.get("route") or "llm"),
                            "model": str(state.get("model") or ""),
                        },
                        "state": state,
                    }
                raise
            state["fragment"] = fragment
            if bool(state.get("verify")):
                state["phase"] = "verify"
                return {
                    "status": "Checking meaning…",
                    "llm": {
                        "prompt": verification_prompt(canonical, fragment),
                        "max_tokens": 160,
                        "temperature": 0.0,
                        "route": str(state.get("route") or "llm"),
                        "model": str(state.get("model") or ""),
                    },
                    "state": state,
                }
            return _presentation(fragment, state, "Formatted")

        if phase == "verify":
            state["verification_input_estimate"] = int((payload or {}).get("input_tokens_estimate") or 0)
            state["verification_output_estimate"] = int((payload or {}).get("output_tokens_estimate") or 0)
            if not llm_text.strip().upper().startswith("PASS"):
                return {
                    "status": "Meaning check failed. Original kept.",
                    "model": str(state.get("used_model") or state.get("model") or ""),
                    "provider": str(state.get("used_provider") or state.get("provider") or ""),
                }
            fragment = sanitize_formatted_html(str(state.get("fragment") or ""))
            assert_protected_tokens(str(state.get("canonical") or ""), fragment)
            return _presentation(fragment, state, "Formatted · meaning checked")
    except FormatContractError as exc:
        return {
            "status": "Formatting failed. Original kept. Exact content could not be preserved.",
            "error_detail": str(exc),
            "model": str(state.get("used_model") or state.get("model") or ""),
            "provider": str(state.get("used_provider") or state.get("provider") or ""),
            "token_usage": {
                "formatting_input_estimate": int(state.get("formatting_input_estimate") or 0),
                "formatting_output_estimate": int(state.get("formatting_output_estimate") or 0),
                "verification_input_estimate": int(state.get("verification_input_estimate") or 0),
                "verification_output_estimate": int(state.get("verification_output_estimate") or 0),
            },
        }
    except Exception as exc:
        return {
            "status": "Formatting failed. Original kept.",
            "error_detail": type(exc).__name__,
            "model": str(state.get("used_model") or state.get("model") or ""),
            "provider": str(state.get("used_provider") or state.get("provider") or ""),
        }
    return {"status": "Formatting failed. Original kept."}
