from __future__ import annotations

import pytest

pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter, QPdfWriter
from PySide6.QtWidgets import QPlainTextEdit

from ui.workspace_previews import WorkspacePreview, preview_kind_for_path


def test_classifies_supported_preview_types() -> None:
    assert preview_kind_for_path("README.md") == "markdown"
    assert preview_kind_for_path("site.HTML") == "html"
    assert preview_kind_for_path("photo.png") == "image"
    assert preview_kind_for_path("manual.pdf") == "pdf"
    assert preview_kind_for_path("people.csv") == "csv"
    assert preview_kind_for_path("main.py") == "text"
    assert preview_kind_for_path("archive.zip") == "unknown"


def test_plain_text_keeps_compatible_editor(qapp) -> None:
    preview = WorkspacePreview()
    assert isinstance(preview.text_editor, QPlainTextEdit)
    assert preview.show_content("hello.txt", "one\ntwo") == "text"
    assert preview.active_widget is preview.text_editor
    assert preview.text_editor.toPlainText() == "one\ntwo"
    assert preview.text_editor.isReadOnly()
    preview.deleteLater()


def test_markdown_renders_without_showing_markup(qapp) -> None:
    preview = WorkspacePreview()
    assert (
        preview.show_content(
            "notes.md",
            "# Heading\n\n**strong**\n\n- [x] Finished\n\n"
            "| Item | State |\n| --- | --- |\n| Preview | Ready |",
        )
        == "markdown"
    )
    plain = preview.markdown_view.toPlainText()
    assert "Heading" in plain
    assert "strong" in plain
    assert "☑ Finished" in plain
    assert "Preview" in plain
    assert "Ready" in plain
    assert "**" not in plain
    assert "| --- |" not in plain
    preview.deleteLater()


def test_html_uses_non_scriptable_network_isolated_renderer(qapp) -> None:
    preview = WorkspacePreview()
    assert preview.show_content("index.html", "<h1>Hello</h1><p>Rendered</p>") == "html"
    assert "Hello" in preview.html_view.toPlainText()
    assert "Rendered" in preview.html_view.toPlainText()
    assert not preview.html_view.openExternalLinks()
    assert not preview.html_view.openLinks()
    preview.deleteLater()


def test_png_bytes_render_as_an_image(qapp) -> None:
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image = QImage(12, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor("#7651c9"))
    assert image.save(buffer, "PNG")
    png = bytes(encoded)
    preview = WorkspacePreview()
    assert preview.show_content("pixel.png", png) == "image"
    assert not preview.image_view.pixmap.isNull()
    preview.deleteLater()


def test_csv_renders_as_a_table(qapp) -> None:
    preview = WorkspacePreview()
    assert preview.show_content("people.csv", "name,score\nAda,10\nLin,12\n") == "csv"
    plain = preview.csv_view.toPlainText()
    assert "name" in plain
    assert "Ada" in plain
    assert "12" in plain
    preview.deleteLater()


def test_pdf_uses_qt_pdf_when_available(qapp) -> None:
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    writer = QPdfWriter(buffer)
    painter = QPainter(writer)
    painter.drawText(100, 100, "OpenWand PDF preview")
    painter.end()
    buffer.close()

    preview = WorkspacePreview()
    result = preview.show_content("report.pdf", bytes(encoded))
    if preview.supports_pdf:
        assert result == "pdf"
        assert preview.active_widget is preview.pdf_view
    else:
        assert result == "fallback"
        assert "not included" in preview.fallback_view.toPlainText()
    preview.deleteLater()


def test_binary_unknown_type_has_readable_fallback(qapp) -> None:
    preview = WorkspacePreview()
    assert preview.show_content("payload.bin", b"\x00\x01\x02") == "fallback"
    assert "No safe preview" in preview.fallback_view.toPlainText()
    preview.deleteLater()


def test_show_path_reads_local_content(qapp, tmp_path) -> None:
    path = tmp_path / "example.json"
    path.write_text('{"ready": true}', encoding="utf-8")
    preview = WorkspacePreview()
    assert preview.show_path(path) == "text"
    assert '"ready": true' in preview.text_editor.toPlainText()
    preview.deleteLater()
