"""Resolve built-in action text for the current assistant language.

The built-in intents are translated across every language in
``core.prompt_i18n.CALLER_INTENT_TEMPLATES`` — label, hint and prompt, not
just the label. A shipped action file names a template instead of hard-coding
English, and the text is resolved when the menu is drawn rather than when the
catalogue is loaded, so switching assistant language needs no reload.

A file that sets its own LABEL, HINT or PROMPT keeps that value. Editing a
built-in to say something else is meant to work.
"""

from __future__ import annotations

from dataclasses import replace

from core.action_files.contracts import ActionCatalog, ActionFile, AppDef, BoundAction, CallerDef
from core.prompt_i18n import caller_intent_template

#: Stable ids for the built-in intents, mapped to their template position.
TEMPLATE_IDS: dict[str, tuple[int, int]] = {
    "general.what_is_this": (0, 0),
    "general.explain_simply": (0, 1),
    "general.how_do_i_fix": (0, 2),
    "rewrite.fix_grammar": (1, 0),
    "rewrite.simplify": (1, 1),
    "rewrite.improve_tone": (1, 2),
}


def is_known_template(template: str) -> bool:
    """Return whether a template id exists."""
    return template in TEMPLATE_IDS


def template_defaults(template: str, language: str | None = None) -> dict[str, str]:
    """Return the label, hint, prompt and default key for one template id."""
    position = TEMPLATE_IDS.get(template)
    if position is None:
        return {}
    return caller_intent_template(position[0], position[1], language)


def resolve_action(action: ActionFile, language: str | None = None) -> ActionFile:
    """Fill an action's empty text fields from its template, if it names one."""
    if not action.template:
        return action
    defaults = template_defaults(action.template, language)
    if not defaults:
        return action
    return replace(
        action,
        label=action.label or str(defaults.get("label") or ""),
        hint=action.hint or str(defaults.get("hint") or ""),
        prompt=action.prompt or str(defaults.get("prompt") or ""),
    )


def _rows(actions: tuple[BoundAction, ...], language: str | None) -> tuple[BoundAction, ...]:
    """Resolve every action in one menu."""
    return tuple(
        BoundAction(key=item.key, action=resolve_action(item.action, language)) for item in actions
    )


def resolve_catalog(catalog: ActionCatalog, language: str | None = None) -> ActionCatalog:
    """Return the catalogue with every built-in resolved for one language."""
    return ActionCatalog(
        root=catalog.root,
        callers=tuple(
            CallerDef(
                folder=caller.folder,
                hotkey=caller.hotkey,
                hotkey_2=caller.hotkey_2,
                label=caller.label,
                enabled=caller.enabled,
                settings=caller.settings,
                actions=_rows(caller.actions, language),
            )
            for caller in catalog.callers
        ),
        apps=tuple(
            AppDef(
                folder=app.folder,
                display_name=app.display_name,
                app=app.app,
                match=app.match,
                actions=_rows(app.actions, language),
            )
            for app in catalog.apps
        ),
        issues=catalog.issues,
    )
