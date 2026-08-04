"""Contract tests for PowerPoint/Google Slides API action foundations."""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from core.actions.adapters.presentation import (
    PowerPointDesktopRuntimeProvider,
    PresentationActionAdapter,
    build_create_slide_plan,
    build_restyle_slide_plan,
    build_speaker_notes_plan,
    is_google_slides_app,
    is_powerpoint_desktop_app,
    is_powerpoint_web_app,
    presentation_backend_for_app,
    presentation_capabilities,
)
from core.actions.adapters.presentation.snapshot import MAX_SLIDES, capture_presentation_snapshot
from core.actions.errors import ActionUnavailableError, ActionValidationError
from core.actions.providers import detected_picker_context
from core.actions.runner import ActionRunner, ActionRuntimeProviderRegistry, PlannedToolCall
from ui.addon_presentations import sanitize_presentation_html


class FakePresentationClient:
    """In-memory stand-in for an explicit Office.js/COM/Slides API client."""

    def __init__(self) -> None:
        self.state = {
            "title": "Quarterly review",
            "revision": "r1",
            "selected_slide_id": "s1",
            "slides": [
                {
                    "slide_id": "s1",
                    "title": "Results",
                    "body": "Revenue increased",
                    "speaker_notes": "Open with the headline.",
                    "style_preset": "clean_light",
                },
                {
                    "slide_id": "s2",
                    "title": "Next steps",
                    "body": "Launch the pilot",
                    "speaker_notes": "",
                    "style_preset": "clean_light",
                },
            ],
        }
        self.calls: list[tuple[str, dict]] = []
        self.rollbacks: dict[str, dict] = {}
        self.revision = 1
        self.corrupt_after_apply = False

    def get_presentation(self, presentation_id: str):
        assert presentation_id == "deck-1"
        return copy.deepcopy(self.state)

    def _receipt(self, method: str, kwargs: dict, slide_id: str) -> dict:
        self.calls.append((method, dict(kwargs)))
        token = f"rollback-{len(self.calls)}"
        self.rollbacks[token] = copy.deepcopy(self.state)
        self.revision += 1
        self.state["revision"] = f"r{self.revision}"
        return {
            "change_id": f"change-{len(self.calls)}",
            "revision": self.state["revision"],
            "slide_id": slide_id,
            "rollback_token": token,
        }

    def create_slide(self, presentation_id: str, **kwargs):
        assert presentation_id == "deck-1"
        receipt = self._receipt("create_slide", kwargs, "s3")
        selected_index = next(
            index for index, slide in enumerate(self.state["slides"])
            if slide["slide_id"] == kwargs["after_slide_id"]
        )
        index = selected_index + 1 if kwargs["position"] == "after_selected" else len(self.state["slides"])
        self.state["slides"].insert(index, {
            "slide_id": "s3",
            "title": kwargs["title"],
            "body": "wrong" if self.corrupt_after_apply else kwargs["body"],
            "speaker_notes": "",
            "style_preset": kwargs["layout"],
        })
        return receipt

    def restyle_slide(self, presentation_id: str, **kwargs):
        assert presentation_id == "deck-1"
        receipt = self._receipt("restyle_slide", kwargs, kwargs["slide_id"])
        slide = next(item for item in self.state["slides"] if item["slide_id"] == kwargs["slide_id"])
        slide["style_preset"] = kwargs["preset"]
        if self.corrupt_after_apply:
            slide["body"] = "corrupted"
        return receipt

    def upsert_speaker_notes(self, presentation_id: str, **kwargs):
        assert presentation_id == "deck-1"
        receipt = self._receipt("upsert_speaker_notes", kwargs, kwargs["slide_id"])
        slide = next(item for item in self.state["slides"] if item["slide_id"] == kwargs["slide_id"])
        slide["speaker_notes"] = kwargs["notes"]
        return receipt

    def rollback(self, presentation_id: str, *, rollback_token: str) -> bool:
        assert presentation_id == "deck-1"
        previous = self.rollbacks.get(rollback_token)
        if previous is None:
            return False
        self.state = copy.deepcopy(previous)
        self.revision += 1
        self.state["revision"] = f"rollback-r{self.revision}"
        return True


def adapter_and_client() -> tuple[PresentationActionAdapter, FakePresentationClient]:
    client = FakePresentationClient()
    return PresentationActionAdapter(
        client,
        backend="google_slides",
        presentation_id="deck-1",
        selected_slide_id="s1",
    ), client


def test_detection_distinguishes_powerpoint_desktop_web_and_google_slides() -> None:
    desktop = {"name": "Pitch.pptx - PowerPoint", "process_name": "POWERPNT.EXE"}
    web = {"name": "Pitch - PowerPoint", "process_name": "msedge.exe", "browser_url": "https://powerpoint.office.com/p/abc"}
    sharepoint = {
        "name": "Pitch.pptx - PowerPoint",
        "process_name": "chrome.exe",
        "browser_url": "https://contoso.sharepoint.com/sites/team/Pitch.pptx",
    }
    slides = {"process_name": "chrome.exe", "browser_url": "https://docs.google.com/presentation/d/abc/edit"}

    assert is_powerpoint_desktop_app(desktop)
    assert is_powerpoint_web_app(web)
    assert is_powerpoint_web_app(sharepoint)
    assert is_google_slides_app(slides)
    assert presentation_backend_for_app(desktop) == "powerpoint_desktop"
    assert presentation_backend_for_app(web) == "powerpoint_officejs"
    assert presentation_backend_for_app(slides) == "google_slides"
    assert presentation_backend_for_app({"browser_url": "https://docs.google.com/document/d/abc"}) == ""
    assert is_powerpoint_web_app({
        "name": "Pitch - PowerPoint - Microsoft Edge",
        "process_name": "msedge.exe",
    })
    assert is_google_slides_app({
        "name": "Pitch - Google Slides - Google Chrome",
        "process_name": "chrome.exe",
    })


def test_capability_schemas_are_closed_and_versioned() -> None:
    capabilities = presentation_capabilities()
    assert {capability.type for capability in capabilities} == {
        "presentation.create_slide@1",
        "presentation.restyle_slide@1",
        "presentation.upsert_speaker_notes@1",
    }
    for capability in capabilities:
        schema = capability.input_schema
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert capability.reversible is True

    office_web = presentation_capabilities("powerpoint_officejs")
    assert {capability.type for capability in office_web} == {
        "presentation.create_slide@1",
        "presentation.restyle_slide@1",
    }


def test_snapshot_is_revision_bound_and_planner_bounded() -> None:
    adapter, _client = adapter_and_client()
    snapshot = adapter.snapshot()

    assert snapshot.target.version == snapshot.fingerprint
    assert snapshot.target.locator["presentation_id"] == "deck-1"
    assert snapshot.model_context()["presentation"]["revision"] == "r1"
    assert len(snapshot.model_context()["slides"]) == 2


def test_snapshot_rejects_missing_revision_and_excess_slides() -> None:
    client = FakePresentationClient()
    client.state["revision"] = ""
    with pytest.raises(ActionUnavailableError, match="revision"):
        capture_presentation_snapshot(client, backend="google_slides", presentation_id="deck-1")

    client.state["revision"] = "r1"
    client.state["slides"] = [
        {"slide_id": f"s{i}", "title": "", "body": "", "speaker_notes": "", "style_preset": ""}
        for i in range(MAX_SLIDES + 1)
    ]
    with pytest.raises(ActionUnavailableError, match="bounded action"):
        capture_presentation_snapshot(client, backend="google_slides", presentation_id="deck-1")


def test_preview_escapes_exact_slide_content_and_is_host_sanitizer_safe() -> None:
    adapter, _client = adapter_and_client()
    snapshot = adapter.snapshot()
    plan = build_create_slide_plan(
        snapshot,
        title="<script>alert(1)</script>",
        body="Q4 <strong>results</strong>",
    )
    preview = adapter.render_preview(plan, snapshot)

    assert "<script>" not in preview.html
    assert "&lt;script&gt;" in preview.html
    assert "&lt;strong&gt;results&lt;/strong&gt;" in preview.html
    assert "Â" not in preview.html
    assert "action-focus-preview" in preview.html
    assert all(text not in preview.html for text in ("Ready to review", "Nothing has changed", "Apply rechecks", "Wisp will"))
    assert sanitize_presentation_html(preview.html) == preview.html


def test_create_slide_executes_once_and_verifies_exact_readback() -> None:
    adapter, client = adapter_and_client()
    plan = build_create_slide_plan(adapter.snapshot(), title="Risks", body="Supply and timing")

    result = adapter.execute(plan, confirmed=True, idempotency_key="create-1")
    repeated = adapter.execute(plan, confirmed=True, idempotency_key="create-1")

    assert result is repeated
    assert result.created == ({"kind": "slide", "name": "s3"},)
    assert result.journal[0]["rollback"] == "presentation_api_rollback"
    assert client.calls[0][0] == "create_slide"
    assert client.calls[0][1]["expected_revision"] == "r1"
    assert client.state["slides"][1]["title"] == "Risks"


def test_restyle_and_notes_use_explicit_api_methods_and_preserve_content() -> None:
    adapter, client = adapter_and_client()
    before = adapter.snapshot().slide("s1")
    style = build_restyle_slide_plan(adapter.snapshot(), preset="executive_blue")
    style_result = adapter.execute(style, confirmed=True, idempotency_key="style-1")
    assert "preserving slide content" in style_result.verification[0]
    assert client.calls[-1][0] == "restyle_slide"
    after_style = adapter.snapshot().slide("s1")
    assert (after_style.title, after_style.body, after_style.speaker_notes) == (
        before.title, before.body, before.speaker_notes
    )

    notes = build_speaker_notes_plan(adapter.snapshot(), notes="Pause, then introduce the pilot.")
    notes_result = adapter.execute(notes, confirmed=True, idempotency_key="notes-1")
    assert notes_result.verification == ("Verified the exact speaker notes through API readback.",)
    assert client.calls[-1][0] == "upsert_speaker_notes"


def test_execute_requires_approval_and_rejects_stale_revision() -> None:
    adapter, client = adapter_and_client()
    plan = build_speaker_notes_plan(adapter.snapshot(), notes="Reviewed notes")
    with pytest.raises(ActionValidationError, match="approve"):
        adapter.execute(plan, confirmed=False, idempotency_key="notes-1")

    client.state["revision"] = "r2"
    with pytest.raises(ActionValidationError, match="revision changed"):
        adapter.execute(plan, confirmed=True, idempotency_key="notes-1")
    assert client.calls == []


def test_verification_failure_rolls_back_semantically() -> None:
    adapter, client = adapter_and_client()
    before = adapter.snapshot().semantic_fingerprint
    client.corrupt_after_apply = True
    plan = build_create_slide_plan(adapter.snapshot(), title="Risks", body="Exact body")

    with pytest.raises(RuntimeError, match="rolled back"):
        adapter.execute(plan, confirmed=True, idempotency_key="create-1")

    assert adapter.snapshot().semantic_fingerprint == before
    assert len(client.state["slides"]) == 2


def test_idempotency_key_cannot_be_reused_for_another_plan_and_journal_can_rollback() -> None:
    adapter, _client = adapter_and_client()
    before = adapter.snapshot().semantic_fingerprint
    first = build_speaker_notes_plan(adapter.snapshot(), notes="First")
    result = adapter.execute(first, confirmed=True, idempotency_key="same-key")
    second = replace(first, plan_id="another-plan")

    with pytest.raises(ActionValidationError, match="another presentation plan"):
        adapter.execute(second, confirmed=True, idempotency_key="same-key")
    assert adapter.rollback(result.journal[0]) is True
    assert adapter.snapshot().semantic_fingerprint == before


def test_powerpoint_runtime_provider_uses_shared_runner_end_to_end() -> None:
    client = FakePresentationClient()
    provider = PowerPointDesktopRuntimeProvider(client)  # type: ignore[arg-type]
    previews = []
    runner = ActionRunner(
        ActionRuntimeProviderRegistry((provider,)),
        planner=lambda **_kwargs: PlannedToolCall(
            tool_name="presentation_plan_create_slide",
            arguments={
                "title": "Customer proof",
                "body": "Three verified outcomes",
                "layout": "title_body",
                "position": "after_selected",
            },
        ),
        approver=lambda preview: previews.append(preview) is None,
        planning_warning_seconds=30,
    )

    outcome = runner.run(
        context={
            "active_app": {
                "name": "deck-1 - PowerPoint",
                "process_name": "POWERPNT.EXE",
            }
        },
        user_prompt="Create a customer proof slide",
        capability_type="presentation.create_slide@1",
        planning_tool_name="presentation_plan_create_slide",
        provider_id="powerpoint_desktop",
    )

    assert outcome.status == "applied"
    assert outcome.result is not None
    assert outcome.result.verification
    assert previews[0].plan_id == outcome.preview.plan_id
    assert client.state["slides"][1]["title"] == "Customer proof"


def test_presentation_picker_exposes_live_desktop_and_gates_web_bridges() -> None:
    desktop = detected_picker_context({
        "active_app": {"name": "Pitch.pptx - PowerPoint", "process_name": "POWERPNT.EXE"}
    })
    slides = detected_picker_context({
        "active_app": {"name": "Pitch - Google Slides", "process_name": "chrome.exe"},
        "browser_url": "https://docs.google.com/presentation/d/deck/edit",
    })

    assert desktop["display_name"] == "Microsoft PowerPoint"
    assert all(item["available"] is True for item in desktop["suggested_intents"])
    assert slides["display_name"] == "Google Slides"
    assert all(item["available"] is False for item in slides["suggested_intents"])
