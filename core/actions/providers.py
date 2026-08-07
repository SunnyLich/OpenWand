"""App detection and intent suggestions for application action providers.

This is deliberately a small picker contract. Runtime execution is delegated
to the shared ActionRunner and its application-specific runtime providers.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

_PLANNING_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


@dataclass(frozen=True)
class ProviderIntentSuggestion:
    """One app-aware shortcut shown alongside the caller's normal intents."""

    id: str
    label: str
    hint: str
    prompt: str
    preferred_key: str = ""
    mode: str = "answer"
    capability_type: str = ""
    planning_tool: str = ""
    available: bool = True
    unavailable_reason: str = ""

    def __post_init__(self) -> None:
        if self.mode not in {"action", "answer", "file"}:
            raise ValueError(f"invalid provider suggestion mode: {self.mode!r}")
        if self.mode == "action" and (not self.capability_type or not self.planning_tool):
            raise ValueError("action suggestions require an exact capability type and planning tool")
        if self.planning_tool and not _PLANNING_TOOL_NAME.fullmatch(self.planning_tool):
            raise ValueError(f"invalid provider planning tool name: {self.planning_tool!r}")
        if not self.available and not self.unavailable_reason.strip():
            raise ValueError("unavailable suggestions require a user-facing reason")

    def to_dict(self) -> dict[str, Any]:
        """Return the UI-safe wire representation."""
        return {
            "id": self.id,
            "label": self.label,
            "hint": self.hint,
            "prompt": self.prompt,
            "preferred_key": self.preferred_key,
            "mode": self.mode,
            "capability_type": self.capability_type,
            "planning_tool": self.planning_tool,
            "available": self.available,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(frozen=True)
class ActionProvider:
    """Detection metadata shared by the picker and the ActionRunner."""

    id: str
    app: str
    display_name: str
    detector: Callable[[dict[str, Any]], bool]
    suggestions: tuple[ProviderIntentSuggestion, ...] = ()

    def detects(self, context: dict[str, Any] | None) -> bool:
        """Return whether this provider owns the captured hotkey context."""
        value = context if isinstance(context, dict) else {}
        try:
            return bool(self.detector(value))
        except Exception:
            return False

    def picker_context(self) -> dict[str, Any]:
        """Return provider metadata that can safely cross the UI worker boundary."""
        return {
            "id": self.id,
            "app": self.app,
            "display_name": self.display_name,
            "suggested_intents": [item.to_dict() for item in self.suggestions],
        }


class ActionProviderRegistry:
    """Ordered registry used to choose exactly one provider for a captured app."""

    def __init__(self, providers: Iterable[ActionProvider] = ()) -> None:
        self._providers: list[ActionProvider] = []
        for provider in providers:
            self.register(provider)

    def register(self, provider: ActionProvider) -> None:
        """Register a provider while preventing ambiguous duplicate identities."""
        if not provider.id.strip():
            raise ValueError("provider id cannot be empty")
        if any(current.id == provider.id for current in self._providers):
            raise ValueError(f"action provider is already registered: {provider.id}")
        self._providers.append(provider)

    def detect(self, context: dict[str, Any] | None) -> ActionProvider | None:
        """Select the first provider matching the pre-overlay app snapshot."""
        for provider in self._providers:
            if provider.detects(context):
                return provider
        return None

    def providers(self) -> tuple[ActionProvider, ...]:
        """Return providers in deterministic detection order."""
        return tuple(self._providers)


def default_action_provider_registry() -> ActionProviderRegistry:
    """Build picker providers from the live app folders."""
    from core.action_files.store import action_runtime_route, live_catalog

    def surface(context: dict[str, Any]) -> dict[str, Any]:
        active = context.get("active_app")
        value = dict(active) if isinstance(active, dict) else dict(context)
        if context.get("browser_url"):
            value["browser_url"] = str(context.get("browser_url") or "")
        return value

    providers: list[ActionProvider] = []
    catalog = live_catalog()
    for app in catalog.apps:
        suggestions_list: list[ProviderIntentSuggestion] = []
        for item in app.actions:
            if not item.action.enabled:
                continue
            capability, planner = action_runtime_route(
                app.folder,
                item.action.name,
                item.action.capability,
                item.action.planner,
                label=item.action.label,
                hint=item.action.hint,
                prompt=item.action.prompt,
            )
            suggestions_list.append(
                ProviderIntentSuggestion(
                    id=item.action.name,
                    label=item.action.label,
                    hint=item.action.hint,
                    prompt=item.action.prompt,
                    preferred_key=item.key,
                    mode="action" if capability else "file" if item.action.has_code else "answer",
                    capability_type=capability,
                    planning_tool=planner,
                    available=item.action.available,
                    unavailable_reason=item.action.unavailable_reason,
                )
            )
        suggestions = tuple(suggestions_list)

        def detects(context: dict[str, Any], *, folder: str = app.folder) -> bool:
            detected = live_catalog().detect_app(surface(context))
            return detected is not None and detected.folder == folder

        providers.append(
            ActionProvider(
                id=app.folder,
                app=app.app,
                display_name=app.display_name,
                detector=detects,
                suggestions=suggestions,
            )
        )
    return ActionProviderRegistry(providers)


def detected_picker_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return picker metadata for the provider owning the captured app, if any."""
    from core.action_files.store import app_picker_context

    return app_picker_context(context)
