"""Localization helpers for preview-first actions.

The action core deliberately emits stable English source strings.  The UI owns
translation so model summaries, file names, cell values, and code remain exact.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from html.parser import HTMLParser

from ui.i18n import t

# This is also the completeness contract used by the locale tests. Dynamic
# values use named placeholders so translators can reorder the sentence.
ACTION_I18N_SOURCES: tuple[str, ...] = (
    "Review action",
    "Apply",
    "Cancel",
    # Calc lifecycle and preview.
    "Checking the active Calc sheet and action connection...",
    "Calc is not ready for a background action.",
    "Reading the selected Calc range and checking its current values...",
    "Selection checked. Validating the exact chart operation...",
    "Building the chart preview from the validated range...",
    "The Calc chart preview could not be prepared.",
    "Preview ready. Waiting for Apply or Cancel; nothing has changed yet.",
    "Chart cancelled. Nothing was changed.",
    "Applying the chart in Calc…",
    "Rechecking the range, creating the reviewed chart, and verifying the result...",
    "Chart created and verified in Calc.",
    "Calc could not verify the reviewed chart action.",
    "This Calc window was opened before OpenWand's background action session. Save your work and restart LibreOffice once; OpenWand will then create charts without taking focus.",
    "Focusless Calc actions are not available in this session. OpenWand did not change the spreadsheet.",
    "Calc chart cancelled. Nothing was changed.",
    "Chart created in LibreOffice Calc.",
    "Calc did not confirm the change.",
    "OpenWand couldn't prepare the Calc chart preview: {error}",
    "OpenWand couldn't create the chart: {error}",
    "Create chart in Calc",
    "CALC ACTION · PREVIEW",
    "OpenWand will add this chart in the same open Calc window.",
    "Workbook",
    "Source",
    "Size",
    "{rows} rows × {columns} columns",
    "Vertical bar chart preview",
    "Nothing has changed yet.",
    "This preview uses the same typed cell values Calc will chart. Apply creates one vertical bar chart; the source cells stay in place.",
    "OpenWand could not find a numeric series in this selection. The final chart may be empty.",
    "Vertical bar chart from {range}",
    "Calc must still be showing the same selected data when you Apply.",
    "Selection checked. Validating the exact Calc operation...",
    "Building the exact preview from the validated range...",
    "The Calc action preview could not be prepared.",
    "The model is still preparing the Calc operation; this may take a few more seconds.",
    "Calc action cancelled. Nothing was changed.",
    "Applying the reviewed action in Calc...",
    "Rechecking the range, applying the reviewed action, and verifying the result...",
    "Calc action applied and verified.",
    "Calc could not verify the reviewed action.",
    "OpenWand couldn't prepare the Calc action preview: {error}",
    "OpenWand couldn't apply the Calc action: {error}",
    "Selection checked. Planning the exact formatting-only changes...",
    "Selection checked. Choosing the exact sort column and direction...",
    "Clean up table in Calc",
    "OpenWand will improve the selected table's presentation without changing its contents.",
    "Cell contents",
    "Unchanged",
    "Exact formatting changes",
    "Proposed appearance",
    "Make the first selected row a clear, bold header",
    "Fit selected columns to their contents",
    "Keep every cell value, formula, and number format unchanged",
    "Apply changes formatting and column widths only.",
    "Format {range} without changing contents",
    "Sort rows in Calc",
    "OpenWand will reorder complete rows; it will not sort one column independently.",
    "Sort by",
    "Direction",
    "Ascending",
    "Descending",
    "Current order",
    "Proposed order",
    "Apply sorts only {range} and keeps the header row in place.",
    "Sort by {label} ({direction})",
    # Excel preview (the desktop Excel adapter is not yet routed by the overlay).
    "Excel changes",
    "EXCEL ACTION · PREVIEW",
    "Review the exact workbook changes before OpenWand applies them.",
    "Create table {name} from {range}",
    "Add {kind} chart {name}",
    "Showing a preview of {rows} rows × {columns} columns.",
    "Preview only — Excel has not been changed.",
    "Apply creates only the reviewed Excel objects.",
    "Creating the table cannot yet be completely undone by OpenWand.",
    "column",
    "line",
    "bar",
    "pie",
    # VS Code lifecycle and preview.
    "Reading the active saved VS Code file and exact selected range...",
    "The active saved file could not be read safely.",
    "This VS Code tab must be saved before OpenWand can change it safely.",
    "Save this tab once, then press Ctrl+Shift+Q again. OpenWand did not change anything.",
    "Recommendation: Press Ctrl+S to choose a filename, then run the same request again.",
    "The saved-file target did not pass safety checks.",
    "Target checked. Drafting the exact contents for the new file...",
    "Target checked. Reviewing the selected code and drafting the exact change...",
    "The model is still drafting the exact code change; this may take a few more seconds.",
    "The code change could not be drafted.",
    "This code action was replaced by a newer request.",
    "Draft received. Checking its file boundary, selected range, and operation schema...",
    "Safety checks passed. Building the exact saved-file diff preview...",
    "The proposed code could not form a safe diff.",
    "Code change cancelled. Nothing was changed.",
    "Rechecking the saved file, applying the reviewed change, and verifying the result...",
    "Reviewed code change applied and verified.",
    "The reviewed code change could not be verified.",
    "The active saved file could not be read.",
    "VS Code change cancelled. Nothing was changed.",
    "Applied the code change in VS Code.",
    "VS Code did not confirm the file change.",
    "OpenWand couldn't prepare the VS Code action: {error}",
    "VS Code fix failed: {error}",
    "OpenWand couldn't build a safe code diff: {error}",
    "OpenWand couldn't apply the code change: {error}",
    "Apply code fix",
    "VS CODE ACTION - PREVIEW",
    "Review the exact saved-file change before OpenWand applies it.",
    "File",
    "Selection",
    "Changed lines",
    "No textual difference was produced.",
    "... diff preview truncated ...",
    "(current)",
    "(proposed)",
    "Apply writes only this fingerprint-checked file range.",
    "Replace selected code in {file}",
    "Apply is refused if the saved file changes after this preview.",
    "OpenWand could not capture the exact Untitled editor target safely.",
    "Keep the caret in the Untitled editor when you press Ctrl+Shift+Q, then try again.",
    "Recommendation: Make sure the text editor itself has focus, not a panel or terminal.",
    "Editor target captured. Reviewing the selected code and drafting the exact change...",
    "Editor insertion point captured. Drafting the exact new content...",
    "Draft received. Checking the captured editor target and exact replacement...",
    "OpenWand couldn't build a safe code diff for the Untitled tab.",
    "Safety checks passed. Building the exact Untitled editor diff preview...",
    "Apply code to Untitled tab",
    "Review the exact change before OpenWand writes it into the captured Untitled editor.",
    "Tab",
    "Target",
    "Selected text",
    "Insertion point",
    "Apply writes only to the editor target captured when you opened OpenWand.",
    "Keep the same Untitled tab open until Apply finishes.",
    "Writing the reviewed change to the captured Untitled editor target...",
    "Reviewed code change written to the Untitled tab.",
    "OpenWand could not write to the captured Untitled editor target.",
    "The Untitled editor target changed before Apply, so OpenWand did not paste the code.",
    "Recommendation: Put the caret back in that tab and run the request again.",
    # Managed browser form lifecycle and preview.
    "Reading safe editable fields from the current browser page...",
    "The browser page is not ready for a safe action.",
    "OpenWand could not inspect this page through its private browser API. Reopen Chrome through OpenWand control and try again.",
    "The browser fields did not pass safety checks.",
    "Found {count} safe field(s). Drafting the exact values to fill...",
    "The model is still matching your request to the page fields; this may take a few more seconds.",
    "The form values could not be drafted.",
    "This browser action was replaced by a newer request.",
    "Draft received. Checking every field, value, and page boundary...",
    "Safety checks passed. Building the exact field-by-field preview...",
    "The proposed values could not form a safe browser action.",
    "Browser form action cancelled. Nothing was changed.",
    "Rechecking the page, filling the reviewed fields, and verifying every value...",
    "Reviewed browser fields filled and verified.",
    "The reviewed browser action could not be verified.",
    "Filled the browser form without submitting it.",
    "The browser did not verify the reviewed field values.",
    "OpenWand couldn't prepare this browser action: {error}",
    "Browser form action failed: {error}",
    "OpenWand couldn't build a safe form preview: {error}",
    "OpenWand couldn't fill the browser form: {error}",
    "Fill web form",
    "BROWSER ACTION - PREVIEW",
    "Review every value before OpenWand fills the current page.",
    "Page",
    "Fields",
    "Submission",
    "Will not submit",
    "Field",
    "Current",
    "Proposed",
    "Empty",
    "Apply fills only these fingerprint-checked fields and does not click Submit.",
    "Fill {label}",
    "Apply is refused if the page or any captured field changes after this preview.",
    # Managed browser form lifecycle and preview.
    "Reading safe editable fields from the current browser page...",
    "The browser page is not ready for a safe action.",
    "OpenWand could not inspect this page through its private browser API. Reopen Chrome through OpenWand control and try again.",
    "The browser fields did not pass safety checks.",
    "Found {count} safe field(s). Drafting the exact values to fill...",
    "The model is still matching your request to the page fields; this may take a few more seconds.",
    "The form values could not be drafted.",
    "This browser action was replaced by a newer request.",
    "Draft received. Checking every field, value, and page boundary...",
    "Safety checks passed. Building the exact field-by-field preview...",
    "The proposed values could not form a safe browser action.",
    "Browser form action cancelled. Nothing was changed.",
    "Rechecking the page, filling the reviewed fields, and verifying every value...",
    "Reviewed browser fields filled and verified.",
    "The reviewed browser action could not be verified.",
    "Filled the browser form without submitting it.",
    "The browser did not verify the reviewed field values.",
    "OpenWand couldn't prepare this browser action: {error}",
    "Browser form action failed: {error}",
    "OpenWand couldn't build a safe form preview: {error}",
    "OpenWand couldn't fill the browser form: {error}",
    "Fill web form",
    "BROWSER ACTION - PREVIEW",
    "Review every value before OpenWand fills the current page.",
    "Page",
    "Fields",
    "Submission",
    "Will not submit",
    "Field",
    "Current",
    "Proposed",
    "Empty",
    "Apply fills only these fingerprint-checked fields and does not click Submit.",
    "Fill {label}",
    "Apply is refused if the page or any captured field changes after this preview.",
    "OpenWand could not capture the exact Untitled editor target safely.",
    "Keep the caret in the Untitled editor when you press Ctrl+Shift+Q, then try again.",
    "Recommendation: Make sure the text editor itself has focus, not a panel or terminal.",
    "Editor target captured. Reviewing the selected code and drafting the exact change...",
    "Editor insertion point captured. Drafting the exact new content...",
    "Draft received. Checking the captured editor target and exact replacement...",
    "OpenWand couldn't build a safe code diff for the Untitled tab.",
    "Safety checks passed. Building the exact Untitled editor diff preview...",
    "Apply code to Untitled tab",
    "Review the exact change before OpenWand writes it into the captured Untitled editor.",
    "Tab",
    "Target",
    "Selected text",
    "Insertion point",
    "Apply writes only to the editor target captured when you opened OpenWand.",
    "Keep the same Untitled tab open until Apply finishes.",
    "Writing the reviewed change to the captured Untitled editor target...",
    "Reviewed code change written to the Untitled tab.",
    "OpenWand could not write to the captured Untitled editor target.",
    "The Untitled editor target changed before Apply, so OpenWand did not paste the code.",
    "Recommendation: Put the caret back in that tab and run the request again.",
    # Cross-application semantic interaction lifecycle.
    "Identifying the recorded application window...",
    "Reading the bounded semantic targets...",
    "Resolving the registered semantic operations...",
    "Checking targets and preconditions...",
    "Building the exact interaction preview...",
    "Waiting for Apply; nothing has changed.",
    "The interaction plan was refused safely.",
    "Cancelled before any interaction changes.",
    "Cancelled after {done} of {total} operations.",
    "Applying step {step} of {total}: {operation}...",
    "Verifying the exact semantic results...",
    "Applied and verified {count} semantic operations.",
    "The interaction stopped safely before continuing.",
    "Set value to {value}",
    "Set toggle to {state}",
    "Scroll by {amount} bounded units",
    "Select this exact item",
    "Invoke this exact control",
    "Read a bounded accessibility tree",
)


_DYNAMIC_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?P<rows>\d+) rows × (?P<columns>\d+) columns"), "{rows} rows × {columns} columns"),
    (re.compile(r"Vertical bar chart from (?P<range>.+)"), "Vertical bar chart from {range}"),
    (re.compile(r"Format (?P<range>.+) without changing contents"), "Format {range} without changing contents"),
    (
        re.compile(r"Apply sorts only (?P<range>.+) and keeps the header row in place\."),
        "Apply sorts only {range} and keeps the header row in place.",
    ),
    (
        re.compile(r"Sort by (?P<label>.+) \((?P<direction>ascending|descending)\)"),
        "Sort by {label} ({direction})",
    ),
    (re.compile(r"Replace selected code in (?P<file>.+)"), "Replace selected code in {file}"),
    (re.compile(r"Create table (?P<name>.+?) from (?P<range>.+)"), "Create table {name} from {range}"),
    (re.compile(r"Add (?P<kind>.+?) chart (?P<name>.+)"), "Add {kind} chart {name}"),
    (
        re.compile(r"Showing a preview of (?P<rows>\d+) rows × (?P<columns>\d+) columns\."),
        "Showing a preview of {rows} rows × {columns} columns.",
    ),
    (re.compile(r"Cancelled after (?P<done>\d+) of (?P<total>\d+) operations\."), "Cancelled after {done} of {total} operations."),
    (
        re.compile(r"Applying step (?P<step>\d+) of (?P<total>\d+): (?P<operation>.+)\.\.\."),
        "Applying step {step} of {total}: {operation}...",
    ),
    (re.compile(r"Applied and verified (?P<count>\d+) semantic operations\."), "Applied and verified {count} semantic operations."),
    (re.compile(r"OpenWand couldn't prepare the Calc chart preview: (?P<error>.+)"), "OpenWand couldn't prepare the Calc chart preview: {error}"),
    (re.compile(r"OpenWand couldn't create the chart: (?P<error>.+)"), "OpenWand couldn't create the chart: {error}"),
    (re.compile(r"OpenWand couldn't prepare the Calc action preview: (?P<error>.+)"), "OpenWand couldn't prepare the Calc action preview: {error}"),
    (re.compile(r"OpenWand couldn't apply the Calc action: (?P<error>.+)"), "OpenWand couldn't apply the Calc action: {error}"),
    (re.compile(r"OpenWand couldn't prepare the VS Code action: (?P<error>.+)"), "OpenWand couldn't prepare the VS Code action: {error}"),
    (re.compile(r"VS Code fix failed: (?P<error>.+)"), "VS Code fix failed: {error}"),
    (re.compile(r"OpenWand couldn't build a safe code diff: (?P<error>.+)"), "OpenWand couldn't build a safe code diff: {error}"),
    (re.compile(r"OpenWand couldn't apply the code change: (?P<error>.+)"), "OpenWand couldn't apply the code change: {error}"),
    (re.compile(r"Found (?P<count>\d+) safe field\(s\)\. Drafting the exact values to fill\.\.\."), "Found {count} safe field(s). Drafting the exact values to fill..."),
    (re.compile(r"OpenWand couldn't prepare this browser action: (?P<error>.+)"), "OpenWand couldn't prepare this browser action: {error}"),
    (re.compile(r"Browser form action failed: (?P<error>.+)"), "Browser form action failed: {error}"),
    (re.compile(r"OpenWand couldn't build a safe form preview: (?P<error>.+)"), "OpenWand couldn't build a safe form preview: {error}"),
    (re.compile(r"OpenWand couldn't fill the browser form: (?P<error>.+)"), "OpenWand couldn't fill the browser form: {error}"),
    (re.compile(r"Fill (?P<label>.+)"), "Fill {label}"),
    (re.compile(r"Found (?P<count>\d+) safe field\(s\)\. Drafting the exact values to fill\.\.\."), "Found {count} safe field(s). Drafting the exact values to fill..."),
    (re.compile(r"OpenWand couldn't prepare this browser action: (?P<error>.+)"), "OpenWand couldn't prepare this browser action: {error}"),
    (re.compile(r"Browser form action failed: (?P<error>.+)"), "Browser form action failed: {error}"),
    (re.compile(r"OpenWand couldn't build a safe form preview: (?P<error>.+)"), "OpenWand couldn't build a safe form preview: {error}"),
    (re.compile(r"OpenWand couldn't fill the browser form: (?P<error>.+)"), "OpenWand couldn't fill the browser form: {error}"),
    (re.compile(r"Fill (?P<label>.+)"), "Fill {label}"),
    (re.compile(r"Set value to (?P<value>.+)"), "Set value to {value}"),
    (re.compile(r"Set toggle to (?P<state>.+)"), "Set toggle to {state}"),
    (re.compile(r"Scroll by (?P<amount>.+) bounded units"), "Scroll by {amount} bounded units"),
)


def translate_action_text(value: str, *, translator: Callable[[str], str] = t) -> str:
    """Translate one trusted action UI string while preserving dynamic values."""
    text = str(value or "")
    if not text:
        return text
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    body = text.strip()
    for pattern, template in _DYNAMIC_PATTERNS:
        match = pattern.fullmatch(body)
        if match:
            groups = match.groupdict()
            for key in ("operation", "kind", "direction"):
                if key in groups:
                    groups[key] = translator(groups[key])
            return leading + translator(template).format(**groups) + trailing
    if body in ACTION_I18N_SOURCES:
        return leading + translator(body) + trailing
    return text


class _ActionHTMLTranslator(HTMLParser):
    """Translate presentation prose, never arbitrary code or data."""

    def __init__(self, translator: Callable[[str], str]) -> None:
        super().__init__(convert_charrefs=False)
        self.translator = translator
        self.output: list[str] = []
        self.stack: list[tuple[str, frozenset[str]]] = []

    def _attributes(self, attrs: list[tuple[str, str | None]]) -> str:
        rendered: list[str] = []
        for name, raw_value in attrs:
            value = "" if raw_value is None else str(raw_value)
            if name.lower() in {"aria-label", "title"}:
                value = translate_action_text(value, translator=self.translator)
            rendered.append(f' {name}="{html.escape(value, quote=True)}"')
        return "".join(rendered)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.output.append(f"<{tag}{self._attributes(attrs)}>")
        if tag != "br":
            flattened = frozenset(
                item
                for name, value in attrs
                if name.lower() == "class"
                for item in str(value or "").split()
            )
            self.stack.append((tag, flattened))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.output.append(f"<{tag}{self._attributes(attrs)}/>")

    def handle_endtag(self, tag: str) -> None:
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        tags = {tag for tag, _classes in self.stack}
        classes = set().union(*(item_classes for _tag, item_classes in self.stack)) if self.stack else set()
        if "code" in tags or "pre" in tags:
            self.output.append(self._translate_diff_metadata(data))
            return
        if "td" in tags or "reply-title" in classes or "target" in classes or "exact-block" in classes:
            self.output.append(data)
            return
        if self.stack and self.stack[-1][0] == "div" and "ticket-field" in self.stack[-1][1]:
            self.output.append(data)
            return
        self.output.append(translate_action_text(data, translator=self.translator))

    def handle_entityref(self, name: str) -> None:
        self.output.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.output.append(f"&#{name};")

    def _translate_diff_metadata(self, data: str) -> str:
        lines: list[str] = []
        for line in data.splitlines(keepends=True):
            ending = "\n" if line.endswith("\n") else ""
            body = line[:-1] if ending else line
            if body == "No textual difference was produced." or body == "... diff preview truncated ...":
                body = self.translator(body)
            elif body.startswith(("--- ", "+++ ")):
                body = re.sub(
                    r" \((current|proposed)\)$",
                    lambda match: " " + self.translator(f"({match.group(1)})"),
                    body,
                )
            lines.append(body + ending)
        return "".join(lines)


def localize_action_preview_html(fragment: str, *, translator: Callable[[str], str] = t) -> str:
    """Localize action-controlled HTML text without changing user content."""
    parser = _ActionHTMLTranslator(translator)
    parser.feed(str(fragment or ""))
    parser.close()
    return "".join(parser.output)


__all__ = ["ACTION_I18N_SOURCES", "localize_action_preview_html", "translate_action_text"]
