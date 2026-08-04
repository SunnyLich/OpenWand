"""Native, network-isolated previews for files in Wisp's shared workspace.

The widget deliberately uses Qt's document and media renderers rather than an
OS browser.  Merely switching a preview never launches another application or
requests keyboard focus.
"""

from __future__ import annotations

import csv
import html
import io
from pathlib import Path
from typing import Final

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ui.chat_rendering import render_markdown_html

try:  # QtPdf is optional in some intentionally small packaged builds.
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover - exercised by import-isolation tests/builds
    QPdfDocument = None  # type: ignore[assignment]
    QPdfView = None  # type: ignore[assignment]


MAX_TEXT_PREVIEW_BYTES: Final = 4 * 1024 * 1024
MAX_MEDIA_PREVIEW_BYTES: Final = 32 * 1024 * 1024

MARKDOWN_SUFFIXES: Final = frozenset({".md", ".markdown", ".mdown", ".mkd"})
HTML_SUFFIXES: Final = frozenset({".html", ".htm", ".xhtml"})
PDF_SUFFIXES: Final = frozenset({".pdf"})
CSV_SUFFIXES: Final = frozenset({".csv", ".tsv"})
TEXT_SUFFIXES: Final = frozenset(
    {
        ".txt", ".log", ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx",
        ".css", ".scss", ".less", ".json", ".jsonl", ".yaml", ".yml",
        ".toml", ".ini", ".cfg", ".conf", ".xml", ".svg", ".sql",
        ".sh", ".ps1", ".bat", ".cmd", ".c", ".h",
        ".cpp", ".hpp", ".cs", ".java", ".kt", ".go", ".rs", ".rb",
        ".php", ".swift", ".r", ".tex", ".gitignore", ".env",
    }
)


def _image_suffixes() -> frozenset[str]:
    """Return formats the running Qt installation can actually decode."""
    return frozenset(f".{bytes(item).decode('ascii', 'ignore').lower()}" for item in QImageReader.supportedImageFormats())


def preview_kind_for_path(path: str | Path) -> str:
    """Classify a file using stable public preview-kind names."""
    suffix = Path(str(path)).suffix.casefold()
    if suffix in MARKDOWN_SUFFIXES:
        return "markdown"
    if suffix in HTML_SUFFIXES:
        return "html"
    if suffix in PDF_SUFFIXES:
        return "pdf"
    if suffix in CSV_SUFFIXES:
        return "csv"
    if suffix in _image_suffixes():
        return "image"
    if suffix in TEXT_SUFFIXES or not suffix:
        return "text"
    return "unknown"


def _decode_text(data: bytes) -> str:
    """Decode common workspace text without ever failing the whole preview."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig")
    return data.decode("utf-8", errors="replace")


class _IsolatedRichText(QTextBrowser):
    """Qt rich-text renderer with links and all external resources disabled."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("workspaceRichPreview")

    def loadResource(self, resource_type, name):  # noqa: N802, ANN001
        # QTextBrowser has no JavaScript engine.  Blocking resources as well
        # prevents HTML/CSS/Markdown from making network or arbitrary file reads.
        del resource_type, name
        return QByteArray()


class _ImagePreview(QScrollArea):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceImagePreview")
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setWidget(self._label)
        self._source = QPixmap()

    @property
    def pixmap(self) -> QPixmap:
        return self._source

    def set_data(self, data: bytes) -> bool:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._source = QPixmap()
            self._label.clear()
            return False
        self._source = pixmap
        self._fit()
        return True

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._source.isNull():
            return
        available = self.viewport().size()
        if available.width() < 2 or available.height() < 2:
            return
        if self._source.width() <= available.width() and self._source.height() <= available.height():
            shown = self._source
        else:
            shown = self._source.scaled(
                available,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._label.setPixmap(shown)


class WorkspacePreview(QWidget):
    """One reusable surface for text, Markdown, HTML, images, and PDFs.

    Use :meth:`show_content` when bytes already arrived from the workspace API,
    or :meth:`show_path` for a local scoped file. ``text_editor`` remains public
    so the existing collaborative caret/typing animation can target it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspacePreview")
        self._active_kind = "empty"
        self._active_path = ""
        self._pdf_buffer: QBuffer | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack)

        self.text_editor = QPlainTextEdit()
        self.text_editor.setObjectName("workspaceTextEditor")
        self.text_editor.setReadOnly(True)
        self.stack.addWidget(self.text_editor)

        self.markdown_view = _IsolatedRichText()
        self.stack.addWidget(self.markdown_view)

        self.html_view = _IsolatedRichText()
        self.stack.addWidget(self.html_view)

        self.csv_view = _IsolatedRichText()
        self.stack.addWidget(self.csv_view)

        self.image_view = _ImagePreview()
        self.stack.addWidget(self.image_view)

        self.pdf_view = None
        self.pdf_document = None
        if QPdfDocument is not None and QPdfView is not None:
            self.pdf_document = QPdfDocument(self)
            self.pdf_view = QPdfView()
            self.pdf_view.setObjectName("workspacePdfPreview")
            self.pdf_view.setDocument(self.pdf_document)
            self.pdf_view.setPageMode(QPdfView.PageMode.MultiPage)
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.stack.addWidget(self.pdf_view)

        self.fallback_view = _IsolatedRichText()
        self.stack.addWidget(self.fallback_view)
        self.clear()

    @property
    def active_kind(self) -> str:
        return self._active_kind

    @property
    def active_path(self) -> str:
        return self._active_path

    @property
    def active_widget(self) -> QWidget:
        return self.stack.currentWidget()

    @property
    def supports_pdf(self) -> bool:
        return self.pdf_view is not None

    def clear(self, message: str = "Select a file to preview it.") -> None:
        self._release_pdf()
        self._active_kind = "empty"
        self._active_path = ""
        self.fallback_view.setHtml(f"<p>{_escape(message)}</p>")
        self.stack.setCurrentWidget(self.fallback_view)

    def show_path(self, path: str | Path) -> str:
        """Read and display a local file, enforcing preview size limits."""
        source = Path(path)
        try:
            size = source.stat().st_size
        except OSError as exc:
            return self._show_error(source.name, f"Could not read this file: {exc}")
        kind = preview_kind_for_path(source)
        limit = MAX_TEXT_PREVIEW_BYTES if kind in {"text", "markdown", "html", "csv", "unknown"} else MAX_MEDIA_PREVIEW_BYTES
        if size > limit:
            return self._show_error(source.name, f"Preview unavailable: file is larger than {limit // (1024 * 1024)} MB.")
        try:
            data = source.read_bytes()
        except OSError as exc:
            return self._show_error(source.name, f"Could not read this file: {exc}")
        return self.show_content(source.name, data)

    def show_content(self, path: str | Path, content: str | bytes | bytearray) -> str:
        """Display already-scoped content and return the selected preview kind."""
        name = str(path)
        kind = preview_kind_for_path(name)
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        limit = MAX_TEXT_PREVIEW_BYTES if kind in {"text", "markdown", "html", "csv", "unknown"} else MAX_MEDIA_PREVIEW_BYTES
        if len(data) > limit:
            return self._show_error(name, f"Preview unavailable: file is larger than {limit // (1024 * 1024)} MB.")

        self._release_pdf()
        self._active_path = name
        if kind == "markdown":
            # Keep the file as plain Markdown.  The richer chat-style HTML exists
            # only inside this isolated preview widget and is never written back.
            self.markdown_view.setHtml(render_markdown_html(_decode_text(data)))
            return self._activate("markdown", self.markdown_view)
        if kind == "html":
            # QTextBrowser is a native, non-scriptable HTML subset renderer;
            # _IsolatedRichText additionally blocks links and every resource.
            self.html_view.setHtml(_decode_text(data))
            return self._activate("html", self.html_view)
        if kind == "csv":
            self.csv_view.setHtml(_csv_document(_decode_text(data), delimiter="\t" if name.casefold().endswith(".tsv") else ","))
            return self._activate("csv", self.csv_view)
        if kind == "image":
            if self.image_view.set_data(data):
                return self._activate("image", self.image_view)
            return self._show_error(name, "Qt could not decode this image.")
        if kind == "pdf":
            if self.pdf_document is None or self.pdf_view is None:
                return self._show_error(name, "PDF preview is not included in this Wisp build.")
            self._pdf_buffer = QBuffer(self)
            self._pdf_buffer.setData(QByteArray(data))
            if not self._pdf_buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                return self._show_error(name, "Could not open this PDF in memory.")
            error = self.pdf_document.load(self._pdf_buffer)
            if error not in (None, QPdfDocument.Error.None_):
                return self._show_error(name, "Qt could not decode this PDF.")
            return self._activate("pdf", self.pdf_view)
        if kind == "unknown" and b"\x00" in data[:4096]:
            return self._show_error(name, "No safe preview is available for this binary file.")

        self.text_editor.setPlainText(_decode_text(data))
        return self._activate("text", self.text_editor)

    def show_editor_content(self, path: str | Path, content: str) -> str:
        """Show the raw editable text behind any text-native rich preview."""
        self._release_pdf()
        self._active_path = str(path)
        self.text_editor.setPlainText(str(content))
        return self._activate("text", self.text_editor)

    def _activate(self, kind: str, widget: QWidget) -> str:
        self._active_kind = kind
        self.stack.setCurrentWidget(widget)
        return kind

    def _show_error(self, path: str, message: str) -> str:
        self._release_pdf()
        self._active_kind = "fallback"
        self._active_path = str(path)
        self.fallback_view.setHtml(f"<h3>{_escape(Path(str(path)).name)}</h3><p>{_escape(message)}</p>")
        self.stack.setCurrentWidget(self.fallback_view)
        return "fallback"

    def _release_pdf(self) -> None:
        if self.pdf_document is not None and self.pdf_document.status() != QPdfDocument.Status.Null:
            self.pdf_document.close()
        if self._pdf_buffer is not None:
            self._pdf_buffer.close()
            self._pdf_buffer.deleteLater()
            self._pdf_buffer = None


def _escape(value: str) -> str:
    return html.escape(str(value), quote=True)


def _csv_document(value: str, *, delimiter: str) -> str:
    """Build a bounded table; the complete file remains available in storage."""
    rows: list[list[str]] = []
    truncated = False
    try:
        for index, row in enumerate(csv.reader(io.StringIO(value), delimiter=delimiter)):
            if index >= 500:
                truncated = True
                break
            rows.append([str(cell) for cell in row[:50]])
            truncated = truncated or len(row) > 50
    except csv.Error as exc:
        return f"<p>Could not parse this table: {_escape(exc)}</p>"
    if not rows:
        return "<p>This table is empty.</p>"
    head, *body = rows
    parts = [
        "<style>table{border-collapse:collapse;width:100%}th,td{border:1px solid #555;padding:6px 8px;text-align:left}th{font-weight:600}</style>",
        "<table><thead><tr>",
    ]
    parts.extend(f"<th>{_escape(cell)}</th>" for cell in head)
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        parts.extend(f"<td>{_escape(cell)}</td>" for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table>")
    if truncated:
        parts.append("<p><em>Preview limited to 500 rows and 50 columns.</em></p>")
    return "".join(parts)


__all__ = [
    "HTML_SUFFIXES",
    "CSV_SUFFIXES",
    "MARKDOWN_SUFFIXES",
    "MAX_MEDIA_PREVIEW_BYTES",
    "MAX_TEXT_PREVIEW_BYTES",
    "PDF_SUFFIXES",
    "TEXT_SUFFIXES",
    "WorkspacePreview",
    "preview_kind_for_path",
]
