"""Literal provider messages with optional, collapsed technical diagnostics."""

from __future__ import annotations

import html
import json
import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit, QToolButton, QVBoxLayout, QWidget

from ui.i18n import t

_NAMES = {
    "google": "Google",
    "openai": "OpenAI",
    "chatgpt": "ChatGPT",
    "groq": "Groq",
    "anthropic": "Anthropic",
    "ollama": "Ollama",
    "copilot": "Copilot",
    "xai": "xAI",
    "zai": "Z.ai",
    "nvidia": "NVIDIA",
    "ai21": "AI21",
    "openrouter": "OpenRouter",
    "deepseek": "DeepSeek",
    "huggingface": "Hugging Face",
    "sambanova": "SambaNova",
}


def error_text(info: dict) -> str:
    provider = str(info.get("provider") or "")
    name = _NAMES.get(provider, provider.title())
    if info.get("source") == "provider" and name:
        title = t("{provider} reported an error").format(provider=name)
    elif name:
        title = t("OpenWand error ({provider})").format(provider=name)
    else:
        title = t("OpenWand reported an error")
    status = info.get("http_status")
    code = str(info.get("code") or "")
    fields = [str(status)] if status else []
    if code and code != str(status):
        fields.append(code)
    if fields:
        title += " · " + " ".join(fields)
    text = title + "\n\n" + str(info.get("message") or "")
    retry = info.get("retry_after_seconds")
    if isinstance(retry, (float, int)) and math.isfinite(retry) and retry >= 0:
        seconds = math.ceil(retry)
        if seconds >= 3600:
            hours, minutes = divmod(math.ceil(seconds / 60), 60)
            duration = f"{hours}h {minutes}m"
        elif seconds >= 60:
            minutes, seconds = divmod(seconds, 60)
            duration = f"{minutes}m {seconds}s"
        else:
            duration = f"{seconds}s"
        label = (
            t("Retry after {duration}.")
            if info.get("retry_source") == "provider"
            else t("OpenWand retry wait: {duration}.")
        )
        text += "\n\n" + label.format(duration=duration)
    return text


def literal_html(text: str) -> str:
    return "<div style='white-space:pre-wrap'>" + html.escape(text).replace("\n", "<br>") + "</div>"


def details_widget(info: dict, parent: QWidget) -> QWidget:
    box = QWidget(parent)
    box.setObjectName("providerErrorDetails")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 2, 0, 2)
    button = QToolButton(box)
    button.setObjectName("providerErrorDetailsToggle")
    button.setText(t("Technical details"))
    button.setCheckable(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    editor = QPlainTextEdit(box)
    editor.setObjectName("providerErrorDetailsText")
    editor.setReadOnly(True)
    editor.setPlainText(json.dumps(info, ensure_ascii=False, indent=2))
    editor.setFixedHeight(180)
    editor.hide()

    def toggle(checked):
        editor.setVisible(checked)
        button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

    button.toggled.connect(toggle)
    layout.addWidget(button)
    layout.addWidget(editor)
    return box
