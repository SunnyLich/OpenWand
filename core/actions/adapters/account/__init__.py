"""Account API action foundations for email and calendars."""

from core.actions.adapters.account.adapter import CalendarAccountActionAdapter, EmailAccountActionAdapter
from core.actions.adapters.account.capabilities import (
    APPLY_CATEGORY,
    CREATE_DISABLED_RULE,
    CREATE_DRAFT,
    CREATE_EVENT,
    RESCHEDULE_EVENT,
    UPDATE_DRAFT,
    calendar_capabilities,
    email_capabilities,
)
from core.actions.adapters.account.detection import (
    detect_calendar_provider,
    detect_email_provider,
    email_suggestion_metadata,
)
from core.actions.adapters.account.plans import build_calendar_plan, build_email_plan
from core.actions.adapters.account.snapshots import CalendarSnapshot, EmailSnapshot

__all__ = [
    "APPLY_CATEGORY", "CREATE_DISABLED_RULE", "CREATE_DRAFT", "CREATE_EVENT", "RESCHEDULE_EVENT", "UPDATE_DRAFT",
    "CalendarAccountActionAdapter", "CalendarSnapshot", "EmailAccountActionAdapter", "EmailSnapshot",
    "build_calendar_plan", "build_email_plan", "calendar_capabilities", "detect_calendar_provider",
    "detect_email_provider", "email_capabilities", "email_suggestion_metadata",
]
