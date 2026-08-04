"""Preview-first actions for Wisp-managed Chromium browsers."""

from core.actions.adapters.browser.adapter import BrowserActionAdapter, BrowserDevToolsTarget, is_browser_app
from core.actions.adapters.browser.capabilities import FILL_FORM, browser_capabilities
from core.actions.adapters.browser.plans import action_plan_from_dict, build_fill_form_plan, parse_form_assignments
from core.actions.adapters.browser.preview import render_browser_form_preview
from core.actions.adapters.browser.snapshot import BrowserField, BrowserFormSnapshot

__all__ = [
    "BrowserActionAdapter",
    "BrowserDevToolsTarget",
    "BrowserField",
    "BrowserFormSnapshot",
    "FILL_FORM",
    "action_plan_from_dict",
    "browser_capabilities",
    "build_fill_form_plan",
    "parse_form_assignments",
    "render_browser_form_preview",
    "is_browser_app",
]
