"""Exact selected-text Rewrite for Wisp-managed Chromium tabs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from core.actions.adapters.browser.adapter import BrowserActionAdapter, _CdpClient


@dataclass(frozen=True)
class BrowserRewriteSnapshot:
    title: str
    url: str
    target_id: str
    kind: str
    element_path: tuple[int, ...]
    start: int
    end: int
    selected_text: str
    container_text: str
    fingerprint: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> BrowserRewriteSnapshot:
        snapshot = cls(
            title=str(value.get("title") or ""),
            url=str(value.get("url") or ""),
            target_id=str(value.get("target_id") or ""),
            kind=str(value.get("kind") or ""),
            element_path=tuple(int(item) for item in (value.get("element_path") or ())),
            start=int(value.get("start") or 0),
            end=int(value.get("end") or 0),
            selected_text=str(value.get("selected_text") or ""),
            container_text=str(value.get("container_text") or ""),
            fingerprint=str(value.get("fingerprint") or ""),
        )
        if snapshot.kind not in {"input", "contenteditable"}:
            raise ValueError("The browser did not expose a supported editable selection.")
        if (
            not snapshot.target_id
            or not snapshot.selected_text
            or snapshot.start < 0
            or snapshot.end <= snapshot.start
            or snapshot.container_text[snapshot.start : snapshot.end] != snapshot.selected_text
        ):
            raise ValueError("The browser returned an invalid exact selected-text target.")
        if snapshot.fingerprint != snapshot.compute_fingerprint():
            raise ValueError("The browser selected-text fingerprint is invalid.")
        return snapshot

    def compute_fingerprint(self) -> str:
        payload = json.dumps(
            [
                self.url,
                self.target_id,
                self.kind,
                self.element_path,
                self.start,
                self.end,
                self.selected_text,
                self.container_text,
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "target_id": self.target_id,
            "kind": self.kind,
            "element_path": list(self.element_path),
            "start": self.start,
            "end": self.end,
            "selected_text": self.selected_text,
            "container_text": self.container_text,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class BrowserRewritePlan:
    snapshot: BrowserRewriteSnapshot
    replacement_text: str

    def to_dict(self) -> dict[str, Any]:
        return {"snapshot": self.snapshot.to_dict(), "replacement_text": self.replacement_text}


class BrowserRewriteAdapter:
    def __init__(self, *, session_token: str = "") -> None:
        self._browser = BrowserActionAdapter(session_token=session_token)

    def inspect_selection(self, active_app: dict[str, Any] | None = None) -> BrowserRewriteSnapshot:
        target = self._browser.discover(active_app)
        client = _CdpClient(target)
        try:
            raw = client.evaluate(_SELECTION_SNAPSHOT_SCRIPT)
        finally:
            client.close()
        if not isinstance(raw, dict) or raw.get("error"):
            raise RuntimeError(str((raw or {}).get("error") or "No editable browser selection was found."))
        raw = dict(raw)
        raw.update({"title": target.title, "url": target.url, "target_id": target.target_id})
        draft = BrowserRewriteSnapshot(
            title=str(raw["title"]),
            url=str(raw["url"]),
            target_id=str(raw["target_id"]),
            kind=str(raw.get("kind") or ""),
            element_path=tuple(int(item) for item in (raw.get("elementPath") or ())),
            start=int(raw.get("start") or 0),
            end=int(raw.get("end") or 0),
            selected_text=str(raw.get("selectedText") or ""),
            container_text=str(raw.get("containerText") or ""),
            fingerprint="",
        )
        return BrowserRewriteSnapshot.from_dict({**draft.to_dict(), "fingerprint": draft.compute_fingerprint()})

    def apply(self, plan: BrowserRewritePlan) -> bool:
        snapshot = plan.snapshot
        target = self._browser.discover(target_id=snapshot.target_id, url=snapshot.url)
        expression = "(" + _SELECTION_APPLY_SCRIPT + ")(" + json.dumps(
            plan.to_dict(), ensure_ascii=False, separators=(",", ":")
        ) + ")"
        client = _CdpClient(target)
        try:
            result = client.evaluate(expression)
        finally:
            client.close()
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(str((result or {}).get("error") or "Browser exact Rewrite failed."))
        expected = (
            snapshot.container_text[: snapshot.start]
            + plan.replacement_text
            + snapshot.container_text[snapshot.end :]
        )
        if str(result.get("containerText") or "") != expected:
            raise RuntimeError("The browser did not verify the exact selected-text replacement.")
        return True


def build_browser_rewrite_plan(
    snapshot: BrowserRewriteSnapshot,
    replacement_text: str,
) -> BrowserRewritePlan:
    replacement = str(replacement_text or "")
    if not replacement:
        raise ValueError("Browser Rewrite returned an empty replacement.")
    return BrowserRewritePlan(snapshot=snapshot, replacement_text=replacement)


_SELECTION_SNAPSHOT_SCRIPT = r"""
(() => {
  const pathOf = (element) => {
    const path = [];
    for (let node = element; node && node !== document.documentElement; node = node.parentElement) {
      if (!node.parentElement) return [];
      path.unshift(Array.prototype.indexOf.call(node.parentElement.children, node));
    }
    return path;
  };
  const active = document.activeElement;
  if (active && /^(INPUT|TEXTAREA)$/.test(active.tagName)) {
    const start = Number(active.selectionStart), end = Number(active.selectionEnd);
    const value = String(active.value || "");
    if (Number.isInteger(start) && end > start) return {
      kind: "input", elementPath: pathOf(active), start, end,
      selectedText: value.slice(start, end), containerText: value
    };
  }
  const selection = window.getSelection();
  if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return {error: "Select editable web text first."};
  const range = selection.getRangeAt(0);
  const node = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
    ? range.commonAncestorContainer : range.commonAncestorContainer.parentElement;
  const root = node && node.closest('[contenteditable="true"], [contenteditable="plaintext-only"]');
  if (!root || !root.contains(range.startContainer) || !root.contains(range.endContainer)) {
    return {error: "The selected web text is not in one supported editable region."};
  }
  const prefix = document.createRange(); prefix.selectNodeContents(root); prefix.setEnd(range.startContainer, range.startOffset);
  const start = prefix.toString().length, selectedText = range.toString(), containerText = root.textContent || "";
  return {kind: "contenteditable", elementPath: pathOf(root), start, end: start + selectedText.length, selectedText, containerText};
})()
"""

_SELECTION_APPLY_SCRIPT = r"""
(plan => {
  const s = plan.snapshot;
  let root = document.documentElement;
  for (const index of s.element_path) { root = root && root.children[index]; }
  if (!root) return {ok:false, error:"The editable web element is no longer present."};
  const current = s.kind === "input" ? String(root.value || "") : String(root.textContent || "");
  if (current !== s.container_text || current.slice(s.start, s.end) !== s.selected_text) {
    return {ok:false, error:"The web text changed after preview."};
  }
  if (s.kind === "input") {
    root.setRangeText(plan.replacement_text, s.start, s.end, "end");
  } else {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let offset = 0, startNode = null, endNode = null, startOffset = 0, endOffset = 0, node;
    while ((node = walker.nextNode())) {
      const next = offset + node.data.length;
      if (!startNode && s.start >= offset && s.start <= next) { startNode = node; startOffset = s.start - offset; }
      if (!endNode && s.end >= offset && s.end <= next) { endNode = node; endOffset = s.end - offset; break; }
      offset = next;
    }
    if (!startNode || !endNode) return {ok:false, error:"The exact DOM text range could not be rebound."};
    const range = document.createRange(); range.setStart(startNode, startOffset); range.setEnd(endNode, endOffset);
    if (range.toString() !== s.selected_text) return {ok:false, error:"The exact DOM selection changed."};
    range.deleteContents(); range.insertNode(document.createTextNode(plan.replacement_text));
  }
  root.dispatchEvent(new InputEvent("input", {bubbles:true, inputType:"insertReplacementText", data:plan.replacement_text}));
  return {ok:true, containerText: s.kind === "input" ? String(root.value || "") : String(root.textContent || "")};
})
"""


__all__ = [
    "BrowserRewriteAdapter",
    "BrowserRewritePlan",
    "BrowserRewriteSnapshot",
    "build_browser_rewrite_plan",
]
