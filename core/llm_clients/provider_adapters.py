"""Explicit transport routing for all provider IDs offered by OpenWand.

Transport support is separate from model capabilities. Compatible services use
one adapter with their own endpoint/credential; unknown providers are rejected.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from core.llm_clients.adapter_protocol import AdapterCapabilityError


class Protocol(StrEnum):
    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"
    ANTHROPIC = "anthropic"
    COPILOT = "copilot_sdk"
    RETIRED = "retired"


@dataclass(frozen=True)
class ProviderAdapter:
    provider: str
    protocol: Protocol
    preserve_reasoning: bool = False


COMPATIBLE_PROVIDERS = frozenset({
    "groq", "openai", "google", "deepseek", "openrouter", "mistral", "xai",
    "together", "cerebras", "zai", "nvidia", "sambanova", "huggingface", "chutes",
    "vercel", "fireworks", "cohere", "ai21", "nebius", "ollama", "custom",
})
PROVIDER_ADAPTERS = {
    provider: ProviderAdapter(provider, Protocol.CHAT_COMPLETIONS, preserve_reasoning=True)
    for provider in COMPATIBLE_PROVIDERS
}
PROVIDER_ADAPTERS.update({
    "chatgpt": ProviderAdapter("chatgpt", Protocol.RESPONSES),
    "anthropic": ProviderAdapter("anthropic", Protocol.ANTHROPIC),
    "copilot": ProviderAdapter("copilot", Protocol.COPILOT),
    "github_models": ProviderAdapter("github_models", Protocol.RETIRED),
})


def adapter_for(provider: str, model: str = "") -> ProviderAdapter:
    from core.custom_connections import is_custom

    provider = (provider or "").strip().lower()
    key = "custom" if is_custom(provider) else provider
    adapter = PROVIDER_ADAPTERS.get(key)
    if adapter is None:
        raise AdapterCapabilityError(f"Unknown model provider: {provider}")
    if adapter.protocol == Protocol.RETIRED:
        raise AdapterCapabilityError("GitHub Models has retired; choose another provider")
    # GPT-6 tool calling requires Responses. Do not guess support for arbitrary
    # custom endpoints or third-party gateways from the model name alone.
    if provider == "openai" and model.lower().startswith("gpt-6"):
        return ProviderAdapter(provider, Protocol.RESPONSES)
    return ProviderAdapter(provider, adapter.protocol, adapter.preserve_reasoning)
