from __future__ import annotations

import pytest

from core.rewrite_office import (
    PowerPointRewriteClient,
    WordRewriteClient,
    build_powerpoint_rewrite_plan,
    build_word_rewrite_plan,
    is_word_desktop_app,
)
from runtime.supervisor.flows import FlowController


class FakeCollection:
    def __init__(self, *items) -> None:
        self.items = list(items)

    @property
    def Count(self) -> int:
        return len(self.items)

    def Item(self, index: int):
        return self.items[index - 1]


class FakeWordRange:
    def __init__(self, document, start: int, end: int) -> None:
        self.document = document
        self.Start = start
        self.End = end

    @property
    def Duplicate(self):
        return FakeWordRange(self.document, self.Start, self.End)

    @property
    def Text(self) -> str:
        return self.document.text[self.Start : self.End]

    @Text.setter
    def Text(self, value: str) -> None:
        self.document.text = (
            self.document.text[: self.Start] + value + self.document.text[self.End :]
        )
        self.End = self.Start + len(value)


class FakeWordDocument:
    def __init__(self, text: str) -> None:
        self.Name = "Draft.docx"
        self.FullName = r"C:\Docs\Draft.docx"
        self.text = text

    def Range(self, start: int, end: int) -> FakeWordRange:
        return FakeWordRange(self, start, end)


class FakeWordApplication:
    def __init__(self, text: str, start: int, end: int) -> None:
        document = FakeWordDocument(text)
        self.ActiveDocument = document
        self.Documents = FakeCollection(document)
        self.Selection = type("Selection", (), {})()
        self.Selection.Range = FakeWordRange(document, start, end)


class FakePowerPointTextRange:
    def __init__(self, shape, start: int, length: int) -> None:
        self.shape = shape
        self.Start = start
        self.Length = length

    @property
    def Text(self) -> str:
        offset = self.Start - 1
        return self.shape.text[offset : offset + self.Length]

    @Text.setter
    def Text(self, value: str) -> None:
        offset = self.Start - 1
        self.shape.text = (
            self.shape.text[:offset]
            + value
            + self.shape.text[offset + self.Length :]
        )
        self.Length = len(value)

    def Characters(self, start: int, length: int):
        return FakePowerPointTextRange(self.shape, start, length)


class FakePowerPointTextFrame:
    def __init__(self, shape) -> None:
        self.shape = shape

    @property
    def HasText(self) -> int:
        return -1 if self.shape.text else 0

    @property
    def TextRange(self) -> FakePowerPointTextRange:
        return FakePowerPointTextRange(self.shape, 1, len(self.shape.text))


class FakePowerPointShape:
    def __init__(self, shape_id: int, text: str) -> None:
        self.Id = shape_id
        self.text = text
        self.HasTextFrame = -1
        self.TextFrame = FakePowerPointTextFrame(self)


class FakePowerPointSlide:
    def __init__(self, slide_id: int, shape: FakePowerPointShape) -> None:
        self.SlideID = slide_id
        self.Shapes = FakeCollection(shape)


class FakePowerPointPresentation:
    def __init__(self, slide: FakePowerPointSlide) -> None:
        self.Name = "Pitch.pptx"
        self.FullName = r"C:\Decks\Pitch.pptx"
        self.Slides = FakeCollection(slide)


class FakePowerPointApplication:
    def __init__(self, text: str, start: int, length: int) -> None:
        shape = FakePowerPointShape(17, text)
        slide = FakePowerPointSlide(42, shape)
        presentation = FakePowerPointPresentation(slide)
        selection = type("Selection", (), {})()
        selection.Type = 3
        selection.TextRange = FakePowerPointTextRange(shape, start, length)
        selection.ShapeRange = FakeCollection(shape)
        view = type("View", (), {"Slide": slide})()
        self.ActiveWindow = type(
            "Window",
            (),
            {"View": view, "Selection": selection},
        )()
        self.ActivePresentation = presentation
        self.Presentations = FakeCollection(presentation)
        self.shape = shape


def test_word_exact_rewrite_captures_applies_and_verifies() -> None:
    application = FakeWordApplication("A rough sentence.", 2, 7)
    client = WordRewriteClient(lambda: application)

    snapshot = client.inspect_selection(
        {"process_name": "WINWORD.EXE", "name": "Draft.docx - Microsoft Word"}
    )
    plan = build_word_rewrite_plan(snapshot, "clear")

    assert snapshot.selected_text == "rough"
    assert client.apply(plan) is True
    assert application.ActiveDocument.text == "A clear sentence."


def test_word_exact_rewrite_refuses_a_stale_range() -> None:
    application = FakeWordApplication("A rough sentence.", 2, 7)
    client = WordRewriteClient(lambda: application)
    snapshot = client.inspect_selection({"process_name": "winword.exe"})
    application.ActiveDocument.text = "A moved sentence."

    with pytest.raises(RuntimeError, match="changed after preview"):
        client.apply(build_word_rewrite_plan(snapshot, "clear"))

    assert application.ActiveDocument.text == "A moved sentence."


def test_word_exact_rewrite_refuses_embedded_object_boundaries() -> None:
    application = FakeWordApplication("Before \x01 after", 7, 8)
    client = WordRewriteClient(lambda: application)

    with pytest.raises(ValueError, match="embedded object boundary"):
        client.inspect_selection({"process_name": "winword.exe"})


def test_powerpoint_exact_rewrite_captures_shape_range_and_applies() -> None:
    application = FakePowerPointApplication("Revenue was good", 13, 4)
    client = PowerPointRewriteClient(lambda: application)

    snapshot = client.inspect_selection(
        {"process_name": "POWERPNT.EXE", "name": "Pitch.pptx - PowerPoint"}
    )
    plan = build_powerpoint_rewrite_plan(snapshot, "strong")

    assert snapshot.slide_id == "42"
    assert snapshot.shape_id == 17
    assert snapshot.selected_text == "good"
    assert client.apply(plan) is True
    assert application.shape.text == "Revenue was strong"


def test_powerpoint_exact_rewrite_refuses_a_changed_shape() -> None:
    application = FakePowerPointApplication("Revenue was good", 13, 4)
    client = PowerPointRewriteClient(lambda: application)
    snapshot = client.inspect_selection({"process_name": "powerpnt.exe"})
    application.shape.text = "Revenue is already strong"

    with pytest.raises(RuntimeError, match="changed after preview"):
        client.apply(build_powerpoint_rewrite_plan(snapshot, "great"))

    assert application.shape.text == "Revenue is already strong"


def test_flow_builds_native_office_rewrite_plans() -> None:
    word_app = FakeWordApplication("A rough sentence.", 2, 7)
    word_snapshot = WordRewriteClient(lambda: word_app).inspect_selection(
        {"process_name": "winword.exe"}
    )
    powerpoint_app = FakePowerPointApplication("Revenue was good", 13, 4)
    powerpoint_snapshot = PowerPointRewriteClient(
        lambda: powerpoint_app
    ).inspect_selection({"process_name": "powerpnt.exe"})

    word_plan = FlowController._build_structured_rewrite_plan(
        {"kind": "word_text_range", "snapshot": word_snapshot},
        "clear",
    )
    powerpoint_plan = FlowController._build_structured_rewrite_plan(
        {"kind": "powerpoint_text_range", "snapshot": powerpoint_snapshot},
        "strong",
    )

    assert word_plan.snapshot is word_snapshot
    assert word_plan.replacement_text == "clear"
    assert powerpoint_plan.snapshot is powerpoint_snapshot
    assert powerpoint_plan.replacement_text == "strong"


def test_flow_captures_exact_word_target(monkeypatch) -> None:
    application = FakeWordApplication("A rough sentence.", 2, 7)
    client = WordRewriteClient(lambda: application)
    monkeypatch.setattr(
        "core.rewrite_office.WordRewriteClient",
        lambda: client,
    )

    target = FlowController._capture_word_rewrite_target(
        {"selected_text": "rough"},
        {"process_name": "winword.exe", "name": "Draft.docx - Microsoft Word"},
    )

    assert target["kind"] == "word_text_range"
    assert target["grid_text"] == "rough"
    assert "Draft.docx" in target["prompt_context"]


def test_flow_does_not_fallback_to_paste_for_word_object_marker(monkeypatch) -> None:
    application = FakeWordApplication("Before \x01 after", 7, 8)
    client = WordRewriteClient(lambda: application)
    monkeypatch.setattr("core.rewrite_office.WordRewriteClient", lambda: client)

    with pytest.raises(ValueError, match="embedded object boundary"):
        FlowController._capture_word_rewrite_target(
            {"selected_text": "\x01"},
            {"process_name": "winword.exe", "name": "Draft.docx - Microsoft Word"},
        )


def test_flow_captures_exact_powerpoint_target(monkeypatch) -> None:
    application = FakePowerPointApplication("Revenue was good", 13, 4)
    client = PowerPointRewriteClient(lambda: application)
    monkeypatch.setattr(
        "core.rewrite_office.PowerPointRewriteClient",
        lambda: client,
    )

    target = FlowController._capture_powerpoint_rewrite_target(
        {"selected_text": "good"},
        {"process_name": "powerpnt.exe", "name": "Pitch.pptx - PowerPoint"},
    )

    assert target["kind"] == "powerpoint_text_range"
    assert target["grid_text"] == "good"
    assert "shape 17" in target["prompt_context"]


def test_word_detection_excludes_browser_tabs() -> None:
    assert is_word_desktop_app(
        {"process_name": "winword.exe", "name": "Draft.docx - Microsoft Word"}
    )
    assert not is_word_desktop_app(
        {"process_name": "msedge.exe", "name": "Draft.docx - Microsoft Word"}
    )
