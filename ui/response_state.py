"""One live assistant turn, shared by Chat and its compact speech bubble."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable

from core.assistant_text import ThoughtStreamParser, merge_segment_iterables
from core.llm_clients.error_details import normalize
from ui.i18n import t
from ui.provider_errors import error_text

log = logging.getLogger("openwand.response_state")


class ResponseState:
    """Own parsing and terminal transitions; surfaces only render this state.

    Mutations and subscribers run on the UI thread. Worker threads send events
    through the existing Qt/IPC queues rather than changing a turn themselves.
    """

    def __init__(self):
        self.id = str(uuid.uuid4())
        self.text = ""
        self.reply_text = ""
        self.segments: list[tuple[str, bool]] = []
        self.status = ""
        self.parser: ThoughtStreamParser | None = ThoughtStreamParser()
        self.response_error = False
        self.provider_error: dict = {}
        self.annotations: list[dict] = []
        self.attachments: list[dict] = []
        self.activities: list[dict] = []
        self.metadata: dict = {}
        self.phase = "streaming"
        self._subscribers: list[Callable] = []

    @property
    def terminal(self) -> bool:
        return self.phase != "streaming"

    def subscribe(self, callback: Callable) -> Callable:
        self._subscribers.append(callback)

        def unsubscribe():
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def notify(self):
        for callback in list(self._subscribers):
            try:
                callback(self)
            except Exception:
                # One closed/broken view must not prevent another view from
                # updating or stop a terminal response from being persisted.
                log.exception("Response view could not render turn %s", self.id)

    def _append(self, text: str, thought: bool):
        if not text:
            return
        self.segments = merge_segment_iterables(self.segments, [(text, thought)])
        if not thought:
            self.reply_text += text

    def feed(self, chunk: object):
        if self.terminal:
            return
        if isinstance(chunk, dict):
            if chunk.get("local_work") or chunk.get("harness_activity"):
                self.activities.append(dict(chunk))
                if not str(chunk.get("text") or ""):
                    self.notify()
                    return
            text = str(chunk.get("text") or "")
            if chunk.get("is_snapshot"):
                # Provider previews and the transformed final answer replace
                # the same turn, without duplicating streamed words or tags.
                self.text = ""
                self.reply_text = ""
                self.segments = []
                self.parser = ThoughtStreamParser()
                self.feed(text)
                return
            thought = bool(chunk.get("is_thought"))
            if chunk.get("is_progress") and not thought:
                self.status = text.strip()
                self.notify()
                return
            self.status = ""
            if thought:
                self._append(text.lstrip("\r\n") if not self.segments else text, True)
                self.notify()
                return
            chunk = text
        self.status = ""
        text = str(chunk or "")
        if (self.segments and self.segments[-1][1] and self.reply_text
                and not self.reply_text.endswith(("\r", "\n")) and not text.startswith(("\r", "\n"))):
            text = "\n" + text
        self.text += text
        if self.parser is None:
            self.parser = ThoughtStreamParser()
        for part, thought in self.parser.feed(text):
            self._append(part, thought)
        self.notify()

    def _flush(self):
        if self.parser is not None:
            for text, thought in self.parser.finish():
                self._append(text, thought)
            self.parser = None

    def set_final(self, text: str):
        if self.terminal:
            return
        self.status = ""
        if text and text != self.text:
            self.text = text
            self.reply_text = ""
            # Preserve the chronological tool/thought transcript supplied by
            # metadata when the provider's final text is the same reply.
            if text != "".join(part for part, thought in self.segments if not thought):
                self.segments = []
                self.parser = ThoughtStreamParser()
                for part, thought in self.parser.feed(text):
                    self._append(part, thought)
            else:
                self.reply_text = text
                self.parser = None
        self._flush()
        self.notify()

    def fail(self, payload: object):
        if self.terminal:
            return
        self._flush()
        self.provider_error = normalize(payload)
        self.response_error = True
        self.annotations = []
        message = error_text(self.provider_error)
        if any(activity.get("local_work") for activity in self.activities):
            message += "\n\n" + t("Completed file operations were kept. Check the file before repeating this request.")
        text = ("\n\n" if self.reply_text else "") + message
        self.text += text
        self._append(text, False)
        self.status = ""
        self.phase = "failed"
        self.notify()

    def finish(self, *, cancelled: bool = False):
        if not self.terminal:
            self._flush()
            self.status = ""
            self.phase = "cancelled" if cancelled else "completed"
            self.notify()


def response_field(name: str) -> property:
    """Keep Chat's established field API backed by the shared turn itself."""
    return property(
        lambda self: getattr(self._response_state, name),
        lambda self, value: setattr(self._response_state, name, value),
    )
