from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.rewrite_libreoffice import (
    LibreOfficeRewriteSnapshot,
    build_libreoffice_rewrite_plan,
    libreoffice_rewrite_surface,
)
from runtime.supervisor.flows import FlowController


class FakeCursor:
    def __init__(self, container) -> None:
        self.container = container
        self.start = 0
        self.length = 0

    def gotoStart(self, _expand: bool) -> None:
        self.start = 0
        self.length = 0

    def goRight(self, count: int, expand: bool) -> None:
        if expand:
            self.length = count
        else:
            self.start += count
            self.length = 0

    def getString(self) -> str:
        return self.container.text[self.start : self.start + self.length]

    def setString(self, value: str) -> None:
        self.container.text = (
            self.container.text[: self.start]
            + value
            + self.container.text[self.start + self.length :]
        )


class FakeContainer:
    def __init__(self, text: str) -> None:
        self.text = text

    def getString(self) -> str:
        return self.text

    def createTextCursor(self) -> FakeCursor:
        return FakeCursor(self)


class FakeUndoManager:
    def __init__(self) -> None:
        self.contexts = []
        self.undo_count = 0

    def enterUndoContext(self, label: str) -> None:
        self.contexts.append(label)

    def leaveUndoContext(self) -> None:
        pass

    def isUndoPossible(self) -> bool:
        return True

    def undo(self) -> None:
        self.undo_count += 1


def _load_helper(monkeypatch):
    monkeypatch.setitem(sys.modules, "uno", SimpleNamespace())
    helper = Path(__file__).resolve().parents[1] / "runtime" / "helpers" / "libreoffice_rewrite.py"
    spec = importlib.util.spec_from_file_location("_wisp_test_libreoffice_rewrite", helper)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_libreoffice_surface_detection_is_suite_specific() -> None:
    assert libreoffice_rewrite_surface(
        {"process_name": "soffice.bin", "name": "Draft.odt — LibreOffice Writer"}
    ) == "writer"
    assert libreoffice_rewrite_surface(
        {"process_name": "soffice.bin", "name": "Pitch.odp — LibreOffice Impress"}
    ) == "impress"
    assert libreoffice_rewrite_surface(
        {"process_name": "soffice.bin", "name": "Budget.ods — LibreOffice Calc"}
    ) == ""


def test_libreoffice_snapshot_contract_rejects_mismatched_offsets() -> None:
    value = {
        "surface": "writer",
        "document_title": "Draft.odt",
        "container_kind": "body",
        "container_name": "",
        "page_index": 0,
        "shape_path": [],
        "start": 2,
        "length": 5,
        "selected_text": "rough",
        "container_text": "A rough sentence.",
        "fingerprint": "hash",
    }
    snapshot = LibreOfficeRewriteSnapshot.from_dict(value)
    plan = build_libreoffice_rewrite_plan(snapshot, "clear")
    assert plan.to_dict()["snapshot"]["selected_text"] == "rough"

    value["start"] = 1
    with pytest.raises(ValueError, match="does not match"):
        LibreOfficeRewriteSnapshot.from_dict(value)


def test_libreoffice_helper_applies_one_exact_writer_range(monkeypatch) -> None:
    helper = _load_helper(monkeypatch)
    container = FakeContainer("A rough sentence.")
    manager = FakeUndoManager()
    document = SimpleNamespace(getUndoManager=lambda: manager)
    snapshot = helper._snapshot_payload(
        "writer",
        SimpleNamespace(Title="Draft.odt"),
        "body",
        "",
        0,
        (),
        2,
        "rough",
        container.text,
    )
    monkeypatch.setattr(helper, "_desktop", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(helper, "_find_document", lambda *_args, **_kwargs: document)
    monkeypatch.setattr(helper, "_writer_container", lambda *_args, **_kwargs: container)

    result = helper.apply("pipe", {"snapshot": snapshot, "replacement_text": "clear"})

    assert result == {"ok": True, "status": "applied", "verification": True}
    assert container.text == "A clear sentence."
    assert manager.contexts == ["Wisp: exact Rewrite"]


def test_flow_builds_libreoffice_rewrite_plan() -> None:
    snapshot = LibreOfficeRewriteSnapshot.from_dict(
        {
            "surface": "impress",
            "document_title": "Pitch.odp",
            "container_kind": "shape",
            "container_name": "Text 1",
            "page_index": 0,
            "shape_path": [2],
            "start": 12,
            "length": 4,
            "selected_text": "good",
            "container_text": "Revenue was good",
            "fingerprint": "hash",
        }
    )

    plan = FlowController._build_structured_rewrite_plan(
        {"kind": "libreoffice_text_range", "snapshot": snapshot},
        "strong",
    )

    assert plan.snapshot is snapshot
    assert plan.replacement_text == "strong"
