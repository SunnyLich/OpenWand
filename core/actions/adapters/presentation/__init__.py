"""Preview-first PowerPoint object-model and Google Slides API foundations."""

from core.actions.adapters.presentation.adapter import PresentationActionAdapter, action_plan_from_dict
from core.actions.adapters.presentation.capabilities import (
    CREATE_SLIDE,
    RESTYLE_SLIDE,
    UPSERT_SPEAKER_NOTES,
    presentation_capabilities,
    presentation_registry,
)
from core.actions.adapters.presentation.client import (
    GoogleSlidesRestClient,
    OfficeJsPowerPointBridge,
    PresentationApiClient,
    PresentationMutationError,
    PresentationMutationReceipt,
)
from core.actions.adapters.presentation.detection import (
    is_google_slides_app,
    is_powerpoint_desktop_app,
    is_powerpoint_web_app,
    presentation_backend_for_app,
)
from core.actions.adapters.presentation.plans import (
    build_create_slide_plan,
    build_restyle_slide_plan,
    build_speaker_notes_plan,
)
from core.actions.adapters.presentation.powerpoint_com import PowerPointComClient
from core.actions.adapters.presentation.preview import render_presentation_preview
from core.actions.adapters.presentation.runtime import PowerPointDesktopRuntimeProvider
from core.actions.adapters.presentation.snapshot import (
    PresentationSnapshot,
    SlideSnapshot,
    capture_presentation_snapshot,
)

__all__ = [
    "CREATE_SLIDE",
    "RESTYLE_SLIDE",
    "UPSERT_SPEAKER_NOTES",
    "PresentationActionAdapter",
    "GoogleSlidesRestClient",
    "OfficeJsPowerPointBridge",
    "PresentationApiClient",
    "PresentationMutationError",
    "PresentationMutationReceipt",
    "PresentationSnapshot",
    "PowerPointComClient",
    "PowerPointDesktopRuntimeProvider",
    "SlideSnapshot",
    "action_plan_from_dict",
    "build_create_slide_plan",
    "build_restyle_slide_plan",
    "build_speaker_notes_plan",
    "capture_presentation_snapshot",
    "is_google_slides_app",
    "is_powerpoint_desktop_app",
    "is_powerpoint_web_app",
    "presentation_backend_for_app",
    "presentation_capabilities",
    "presentation_registry",
    "render_presentation_preview",
]
