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
        if self.mode not in {"action", "answer"}:
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
    """Build the providers currently backed by Wisp application APIs."""
    from core.actions.adapters.account import detect_calendar_provider, detect_email_provider
    from core.actions.adapters.browser import is_browser_app
    from core.actions.adapters.calc import is_calc_app
    from core.actions.adapters.presentation import (
        is_google_slides_app,
        is_powerpoint_desktop_app,
        is_powerpoint_web_app,
    )
    from core.actions.adapters.vscode import is_vscode_app

    def active_app(context: dict[str, Any]) -> dict[str, Any]:
        value = context.get("active_app")
        return value if isinstance(value, dict) else {}

    def active_surface(context: dict[str, Any]) -> dict[str, Any]:
        value = dict(active_app(context))
        if context.get("browser_url"):
            value["browser_url"] = str(context.get("browser_url") or "")
        return value

    account_connection_reason = "Connect this account to Wisp before using account API actions"
    web_bridge_reason = "This app's authenticated Wisp API bridge is not connected yet"

    return ActionProviderRegistry(
        (
            ActionProvider(
                id="powerpoint_desktop",
                app="presentation",
                display_name="Microsoft PowerPoint",
                detector=lambda context: is_powerpoint_desktop_app(active_app(context)),
                suggestions=(
                    ProviderIntentSuggestion(
                        id="powerpoint.create_slide",
                        label="Create a slide",
                        hint="Set title, content, layout, and position",
                        prompt="Create one slide that fits this presentation.",
                        preferred_key="C",
                        mode="action",
                        capability_type="presentation.create_slide@1",
                        planning_tool="presentation_plan_create_slide",
                    ),
                    ProviderIntentSuggestion(
                        id="powerpoint.restyle_slide",
                        label="Restyle this slide",
                        hint="Apply a reviewed preset without changing its content",
                        prompt="Restyle the selected slide while preserving all of its content.",
                        preferred_key="R",
                        mode="action",
                        capability_type="presentation.restyle_slide@1",
                        planning_tool="presentation_plan_restyle_slide",
                    ),
                    ProviderIntentSuggestion(
                        id="powerpoint.speaker_notes",
                        label="Write speaker notes",
                        hint="Preview the exact notes for the selected slide",
                        prompt="Write speaker notes for the selected slide.",
                        preferred_key="N",
                        mode="action",
                        capability_type="presentation.upsert_speaker_notes@1",
                        planning_tool="presentation_plan_speaker_notes",
                    ),
                ),
            ),
            ActionProvider(
                id="gmail",
                app="email",
                display_name="Gmail",
                detector=lambda context: detect_email_provider(context) == "gmail",
                suggestions=(
                    _unavailable_action(
                        "gmail.create_draft", "Create email draft", "Preview recipients, subject, and body",
                        "Create a draft email from my request.", "D", "email.create_draft@1",
                        "email_plan_create_draft", account_connection_reason,
                    ),
                    _unavailable_action(
                        "gmail.apply_category", "Label this email", "Preview the exact Gmail label",
                        "Apply the most appropriate label to this email.", "L", "email.apply_category@1",
                        "email_plan_apply_category", account_connection_reason,
                    ),
                ),
            ),
            ActionProvider(
                id="outlook_calendar",
                app="calendar",
                display_name="Outlook Calendar",
                detector=lambda context: detect_calendar_provider(context) == "outlook",
                suggestions=_calendar_unavailable_suggestions(account_connection_reason),
            ),
            ActionProvider(
                id="google_calendar",
                app="calendar",
                display_name="Google Calendar",
                detector=lambda context: detect_calendar_provider(context) == "google",
                suggestions=_calendar_unavailable_suggestions(account_connection_reason),
            ),
            ActionProvider(
                id="outlook_email",
                app="email",
                display_name="Outlook",
                detector=lambda context: detect_email_provider(context) == "outlook",
                suggestions=(
                    _unavailable_action(
                        "outlook.create_draft", "Create email draft", "Preview recipients, subject, and body",
                        "Create a draft email from my request.", "D", "email.create_draft@1",
                        "email_plan_create_draft", account_connection_reason,
                    ),
                    _unavailable_action(
                        "outlook.apply_category", "Categorize this email", "Preview the exact Outlook category",
                        "Apply the most appropriate category to this email.", "L", "email.apply_category@1",
                        "email_plan_apply_category", account_connection_reason,
                    ),
                    _unavailable_action(
                        "outlook.disabled_rule", "Create a disabled rule", "Preview a rule that starts turned off",
                        "Create a disabled Outlook mail rule from my request.", "U", "email.create_disabled_rule@1",
                        "email_plan_disabled_rule", account_connection_reason,
                    ),
                ),
            ),
            ActionProvider(
                id="powerpoint_web",
                app="presentation",
                display_name="PowerPoint for the web",
                detector=lambda context: is_powerpoint_web_app(active_surface(context)),
                suggestions=_presentation_unavailable_suggestions(web_bridge_reason, include_notes=False),
            ),
            ActionProvider(
                id="google_slides",
                app="presentation",
                display_name="Google Slides",
                detector=lambda context: is_google_slides_app(active_surface(context)),
                suggestions=_presentation_unavailable_suggestions(web_bridge_reason, include_notes=True),
            ),
            ActionProvider(
                id="google_sheets",
                app="spreadsheet",
                display_name="Google Sheets",
                detector=lambda context: _is_google_sheets(active_surface(context)),
                suggestions=(
                    _unavailable_action(
                        "sheets.clean_table", "Clean up this table", "Preview formatting without changing values",
                        "Format the selected cells as a clean table.", "T", "spreadsheet.format_table@1",
                        "spreadsheet_plan_format_table", web_bridge_reason,
                    ),
                    _unavailable_action(
                        "sheets.sort_rows", "Sort these rows", "Preview the complete new row order",
                        "Sort the selected rows by the most relevant column.", "O", "spreadsheet.sort_rows@1",
                        "spreadsheet_plan_sort_rows", web_bridge_reason,
                    ),
                ),
            ),
            ActionProvider(
                id="browser",
                app="browser",
                display_name="Browser",
                detector=lambda context: is_browser_app(active_app(context)),
                suggestions=(
                    ProviderIntentSuggestion(
                        id="browser.fill_form",
                        label="Fill this form",
                        hint="Preview safe visible fields; never submit",
                        prompt="Fill in this form using the information in my selected context.",
                        preferred_key="F",
                        mode="action",
                        capability_type="browser.fill_form",
                        planning_tool="browser_plan_fill_form",
                    ),
                ),
            ),
            ActionProvider(
                id="vscode",
                app="vscode",
                display_name="VS Code",
                detector=lambda context: is_vscode_app(active_app(context)),
                suggestions=(
                    ProviderIntentSuggestion(
                        id="vscode.fix_selection",
                        label="Fix selected code",
                        hint="Preview and apply a focused code change",
                        prompt="Fix the selected code.",
                        preferred_key="F",
                        mode="action",
                        capability_type="vscode.replace_selection@1",
                        planning_tool="vscode_plan_replace_selection",
                    ),
                    ProviderIntentSuggestion(
                        id="vscode.refactor_selection",
                        label="Refactor selection",
                        hint="Improve the selected code without changing its intent",
                        prompt="Refactor and improve the selected code without changing its intended behavior.",
                        preferred_key="R",
                        mode="action",
                        capability_type="vscode.replace_selection@1",
                        planning_tool="vscode_plan_replace_selection",
                    ),
                ),
            ),
            ActionProvider(
                id="libreoffice_calc",
                app="libreoffice_calc",
                display_name="LibreOffice Calc",
                detector=lambda context: is_calc_app(active_app(context)),
                suggestions=(
                    ProviderIntentSuggestion(
                        id="calc.add_chart",
                        label="Create a bar chart",
                        hint="Build a reviewed chart from the selected cells",
                        prompt="Create a vertical bar chart from the selected cells.",
                        preferred_key="C",
                        mode="action",
                        capability_type="calc.add_chart@1",
                        planning_tool="calc_plan_add_chart",
                    ),
                    ProviderIntentSuggestion(
                        id="calc.format_table",
                        label="Clean up this table",
                        hint="Improve headers and spacing without changing values",
                        prompt="Format the selected cells as a clean, readable table.",
                        preferred_key="T",
                        mode="action",
                        capability_type="calc.format_table@1",
                        planning_tool="calc_plan_format_table",
                    ),
                    ProviderIntentSuggestion(
                        id="calc.sort_range",
                        label="Sort this table",
                        hint="Choose a selected column and preview the new row order",
                        prompt="Sort the selected table by the most relevant column in ascending order.",
                        preferred_key="O",
                        mode="action",
                        capability_type="calc.sort_range@1",
                        planning_tool="calc_plan_sort_range",
                    ),
                    ProviderIntentSuggestion(
                        id="calc.analyze_selection",
                        label="Analyze this data",
                        hint="Explain patterns and useful next steps without changing cells",
                        prompt="Analyze the selected spreadsheet data and explain the most useful patterns.",
                        preferred_key="A",
                        mode="answer",
                    ),
                ),
            ),
        )
    )


def _unavailable_action(
    suggestion_id: str,
    label: str,
    hint: str,
    prompt: str,
    preferred_key: str,
    capability_type: str,
    planning_tool: str,
    reason: str,
) -> ProviderIntentSuggestion:
    return ProviderIntentSuggestion(
        id=suggestion_id,
        label=label,
        hint=hint,
        prompt=prompt,
        preferred_key=preferred_key,
        mode="action",
        capability_type=capability_type,
        planning_tool=planning_tool,
        available=False,
        unavailable_reason=reason,
    )


def _calendar_unavailable_suggestions(reason: str) -> tuple[ProviderIntentSuggestion, ...]:
    return (
        _unavailable_action(
            "calendar.create_event", "Create calendar event", "Preview time, guests, and details",
            "Create a calendar event from my request.", "E", "calendar.create_event@1",
            "calendar_plan_create_event", reason,
        ),
        _unavailable_action(
            "calendar.reschedule_event", "Reschedule this event", "Preview the exact old and new time",
            "Reschedule this calendar event.", "R", "calendar.reschedule_event@1",
            "calendar_plan_reschedule_event", reason,
        ),
    )


def _presentation_unavailable_suggestions(
    reason: str,
    *,
    include_notes: bool,
) -> tuple[ProviderIntentSuggestion, ...]:
    suggestions = [
        _unavailable_action(
            "presentation.create_slide", "Create a slide", "Set title, content, layout, and position",
            "Create one slide that fits this presentation.", "C", "presentation.create_slide@1",
            "presentation_plan_create_slide", reason,
        ),
        _unavailable_action(
            "presentation.restyle_slide", "Restyle this slide", "Preview a content-preserving style preset",
            "Restyle the selected slide while preserving its content.", "R", "presentation.restyle_slide@1",
            "presentation_plan_restyle_slide", reason,
        ),
    ]
    if include_notes:
        suggestions.append(_unavailable_action(
            "presentation.speaker_notes", "Write speaker notes", "Preview the exact notes",
            "Write speaker notes for the selected slide.", "N", "presentation.upsert_speaker_notes@1",
            "presentation_plan_speaker_notes", reason,
        ))
    return tuple(suggestions)


def _is_google_sheets(active_app: dict[str, Any]) -> bool:
    from urllib.parse import urlparse

    parsed = urlparse(str(active_app.get("browser_url") or active_app.get("url") or ""))
    if (parsed.hostname or "").casefold() == "docs.google.com" and parsed.path.casefold().startswith(
        "/spreadsheets/"
    ):
        return True
    process = str(active_app.get("process_name") or "").strip().casefold()
    title = str(active_app.get("name") or active_app.get("title") or "").casefold()
    return process in {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"} and "google sheets" in title


def detected_picker_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return picker metadata for the provider owning the captured app, if any."""
    provider = default_action_provider_registry().detect(context)
    return provider.picker_context() if provider is not None else {}
