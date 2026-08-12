"""Focusless browser form actions through a private Chromium DevTools endpoint."""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from core.actions.adapters.browser.capabilities import FILL_FORM, browser_capabilities
from core.actions.adapters.browser.preview import render_browser_form_preview
from core.actions.adapters.browser.snapshot import BrowserField, BrowserFormSnapshot
from core.actions.contracts import ActionExecutionResult, ActionPlan, ActionPreview, ValidationIssue
from core.actions.errors import ActionValidationError

_BROWSER_PROCESSES = {"chrome.exe", "msedge.exe", "brave.exe", "chromium.exe"}


@dataclass(frozen=True)
class BrowserDevToolsTarget:
    port: int
    target_id: str
    title: str
    url: str
    websocket_url: str


class _CdpClient:
    def __init__(self, target: BrowserDevToolsTarget) -> None:
        from websockets.sync.client import connect

        self._socket = connect(
            target.websocket_url,
            origin=f"http://127.0.0.1:{target.port}",
            open_timeout=3.0,
            close_timeout=1.0,
        )
        self._sequence = 0

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._sequence += 1
        request_id = self._sequence
        self._socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        while True:
            payload = json.loads(self._socket.recv(timeout=10.0))
            if payload.get("id") != request_id:
                continue
            if payload.get("error"):
                raise RuntimeError(f"Chromium DevTools {method} failed: {payload['error']}")
            return dict(payload.get("result") or {})

    def evaluate(self, expression: str) -> Any:
        payload = self.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        result = payload.get("result") or {}
        if result.get("subtype") == "error":
            raise RuntimeError(str(result.get("description") or "Browser evaluation failed."))
        return result.get("value")


def is_browser_app(active_app: dict[str, Any] | None) -> bool:
    value = active_app or {}
    process = str(value.get("process_name") or "").casefold()
    title = str(value.get("name") or "").casefold()
    return process in _BROWSER_PROCESSES or any(
        marker in title for marker in ("google chrome", "microsoft edge", "brave", "chromium")
    )


class BrowserActionAdapter:
    """Snapshot, preview, mutate, verify, and roll back one managed browser tab."""

    def __init__(self, *, session_token: str = "") -> None:
        self._idempotent_results: dict[str, ActionExecutionResult] = {}
        self._session_token = str(session_token or os.environ.get("OPENWAND_BROWSER_SESSION_TOKEN") or "").strip()

    def capabilities(self):
        return browser_capabilities()

    def _managed_ports(self) -> set[int]:
        import psutil

        if len(self._session_token) < 16:
            return set()
        ports: set[int] = set()
        for process in psutil.process_iter(["name", "cmdline"]):
            try:
                if str(process.info.get("name") or "").casefold() not in _BROWSER_PROCESSES:
                    continue
                command_line = " ".join(process.info.get("cmdline") or [])
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                continue
            marker = re.search(r"--openwand-managed-session(?:=|\s+)([^\s]+)", command_line)
            if marker is None or marker.group(1) != self._session_token:
                continue
            match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", command_line)
            if match and int(match.group(1)) > 0:
                ports.add(int(match.group(1)))
        return ports

    @staticmethod
    def _targets_for_port(port: int) -> list[BrowserDevToolsTarget]:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.0) as response:
            rows = json.loads(response.read().decode("utf-8"))
        targets: list[BrowserDevToolsTarget] = []
        for row in rows if isinstance(rows, list) else []:
            websocket_url = str(row.get("webSocketDebuggerUrl") or "")
            parsed = urlparse(websocket_url)
            page_url = str(row.get("url") or "")
            if row.get("type") != "page" or parsed.scheme not in {"ws", "wss"}:
                continue
            if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                continue
            if page_url.startswith(("chrome://", "edge://", "devtools://")):
                continue
            targets.append(
                BrowserDevToolsTarget(
                    port=port,
                    target_id=str(row.get("id") or ""),
                    title=str(row.get("title") or ""),
                    url=page_url,
                    websocket_url=websocket_url,
                )
            )
        return targets

    def discover(
        self,
        active_app: dict[str, Any] | None = None,
        *,
        target_id: str = "",
        url: str = "",
    ) -> BrowserDevToolsTarget:
        targets: list[BrowserDevToolsTarget] = []
        for port in sorted(self._managed_ports()):
            try:
                targets.extend(self._targets_for_port(port))
            except Exception:
                continue
        if target_id:
            exact_id = [target for target in targets if target.target_id == target_id]
            if len(exact_id) == 1:
                return exact_id[0]
        expected_url = str(url or (active_app or {}).get("browser_url") or (active_app or {}).get("url") or "")
        if expected_url:
            exact_url = [target for target in targets if target.url == expected_url]
            if len(exact_url) == 1:
                return exact_url[0]
        expected_title = self._clean_window_title(str((active_app or {}).get("name") or ""))
        if expected_title:
            exact_title = [
                target for target in targets if self._clean_window_title(target.title) == expected_title
            ]
            if len(exact_title) == 1:
                return exact_title[0]
        if len(targets) == 1:
            return targets[0]
        if not targets:
            raise RuntimeError("This browser was not opened with OpenWand's private managed action session.")
        raise RuntimeError("OpenWand could not identify one unique managed browser tab.")

    @staticmethod
    def _clean_window_title(title: str) -> str:
        value = " ".join(str(title or "").casefold().split())
        return re.sub(r"\s+-\s+(google chrome|microsoft edge|brave|chromium)$", "", value)

    def inspect_form(self, active_app: dict[str, Any] | None = None) -> BrowserFormSnapshot:
        target = self.discover(active_app)
        return self._inspect_target(target)

    def _inspect_target(self, target: BrowserDevToolsTarget) -> BrowserFormSnapshot:
        client = _CdpClient(target)
        try:
            client.call("Runtime.enable")
            raw = client.evaluate(_FORM_SNAPSHOT_SCRIPT)
        finally:
            client.close()
        if not isinstance(raw, dict):
            raise RuntimeError("The browser did not return a form snapshot.")
        fields: list[BrowserField] = []
        for index, item in enumerate(raw.get("fields") or (), 1):
            if not isinstance(item, dict):
                continue
            fields.append(
                BrowserField(
                    field_id=f"field_{index}",
                    selector=str(item.get("selector") or ""),
                    label=str(item.get("label") or f"Field {index}")[:200],
                    kind=str(item.get("kind") or "text"),
                    value=str(item.get("value") or "")[:4_000],
                    placeholder=str(item.get("placeholder") or "")[:200],
                    required=bool(item.get("required")),
                    options=tuple(str(option)[:500] for option in (item.get("options") or ())[:200]),
                )
            )
        if not fields:
            raise RuntimeError("No safe, editable form fields were found on this page.")
        field_tuple = tuple(fields)
        page_url = str(raw.get("url") or target.url)
        return BrowserFormSnapshot(
            title=str(raw.get("title") or target.title),
            url=page_url,
            target_id=target.target_id,
            fields=field_tuple,
            fingerprint=BrowserFormSnapshot.compute_fingerprint(page_url, field_tuple),
        )

    def validate(self, plan: ActionPlan, snapshot: BrowserFormSnapshot) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        if plan.app != "browser":
            issues.append(ValidationIssue("wrong_adapter", "This action is not for a browser."))
        if plan.target.locator != snapshot.target.locator:
            issues.append(ValidationIssue("target_changed", "The browser tab changed after the preview."))
        if plan.target.version != snapshot.fingerprint:
            issues.append(ValidationIssue("target_stale", "The page or a captured form value changed after the preview."))
        fields = {field.field_id: field for field in snapshot.fields}
        if not plan.operations or len(plan.operations) > 20:
            issues.append(ValidationIssue("unsupported_plan", "The browser plan must fill 1 to 20 fields."))
        for operation in plan.operations:
            field = fields.get(str(operation.args.get("field_id") or ""))
            if operation.type != FILL_FORM or field is None:
                issues.append(ValidationIssue("unsupported_operation", "The browser plan references an unavailable field.", operation.id))
                continue
            if operation.args.get("selector") != field.selector or operation.args.get("expected_value") != field.value:
                issues.append(ValidationIssue("field_stale", f"{field.label} changed after the preview.", operation.id))
        return tuple(issues)

    def render_preview(self, plan: ActionPlan, snapshot: BrowserFormSnapshot) -> ActionPreview:
        issues = self.validate(plan, snapshot)
        if issues:
            raise ActionValidationError(issues)
        return render_browser_form_preview(plan)

    def execute(self, plan: ActionPlan, *, confirmed: bool, idempotency_key: str) -> ActionExecutionResult:
        if plan.requires_confirmation and not confirmed:
            raise ActionValidationError(
                (ValidationIssue("confirmation_required", "Review and Apply the browser preview first."),)
            )
        if not idempotency_key.strip():
            raise ActionValidationError(
                (ValidationIssue("idempotency_required", "The browser action is missing its execution key."),)
            )
        cached = self._idempotent_results.get(idempotency_key)
        if cached is not None:
            return cached
        target = self.discover(
            target_id=str(plan.target.locator.get("target_id") or ""),
            url=str(plan.target.locator.get("url") or ""),
        )
        current = self._inspect_target(target)
        issues = self.validate(plan, current)
        if issues:
            raise ActionValidationError(issues)
        assignments = [
            {
                "selector": str(operation.args["selector"]),
                "expected": str(operation.args.get("expected_value") or ""),
                "value": str(operation.args.get("value") or ""),
            }
            for operation in plan.operations
        ]
        outcome = self._apply(target, assignments)
        if not outcome.get("ok"):
            raise RuntimeError(str(outcome.get("error") or "The browser did not verify the form changes."))
        result = ActionExecutionResult(
            plan_id=plan.plan_id,
            status="applied",
            message=f"Filled and verified {len(assignments)} field(s) without submitting the form.",
            created=(),
            journal=tuple(
                {
                    "kind": "browser_field",
                    "selector": assignment["selector"],
                    "before": assignment["expected"],
                    "rollback": "restore_value",
                }
                for assignment in assignments
            ),
            verification=(
                f"Verified {len(assignments)} exact field value(s) in the same browser tab.",
                "No submit button, physical keyboard, or physical mouse was used.",
            ),
        )
        self._idempotent_results[idempotency_key] = result
        return result

    @staticmethod
    def _apply(target: BrowserDevToolsTarget, assignments: list[dict[str, str]]) -> dict[str, Any]:
        client = _CdpClient(target)
        encoded = json.dumps(assignments, ensure_ascii=False)
        try:
            client.call("Runtime.enable")
            outcome = client.evaluate(_FORM_APPLY_SCRIPT.replace("__OPENWAND_ASSIGNMENTS__", encoded))
            if not isinstance(outcome, dict):
                raise RuntimeError("The browser returned an invalid Apply result.")
            return outcome
        finally:
            client.close()


_FORM_SNAPSHOT_SCRIPT = r"""
(() => {
  const allowed = new Set(['text', 'email', 'tel', 'url', 'search', 'number', 'date']);
  const cssPath = element => {
    if (element.id) return `#${CSS.escape(element.id)}`;
    const parts = [];
    let node = element;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      const tag = node.tagName.toLowerCase();
      const siblings = [...(node.parentElement?.children || [])].filter(item => item.tagName === node.tagName);
      parts.unshift(`${tag}:nth-of-type(${siblings.indexOf(node) + 1})`);
      node = node.parentElement;
    }
    return `html > ${parts.join(' > ')}`;
  };
  const labelFor = element => {
    const explicit = element.labels?.length ? [...element.labels].map(item => item.innerText).join(' ') : '';
    return (explicit || element.getAttribute('aria-label') || element.placeholder || element.name || element.id || element.tagName)
      .replace(/\s+/g, ' ').trim();
  };
  const fields = [...document.querySelectorAll('input, textarea, select')]
    .filter(element => {
      if (element.disabled || element.readOnly || element.hidden || element.getAttribute('aria-hidden') === 'true') return false;
      if (element.getClientRects().length === 0) return false;
      if (element instanceof HTMLInputElement && !allowed.has((element.type || 'text').toLowerCase())) return false;
      return true;
    })
    .map(element => ({
      selector: cssPath(element),
      label: labelFor(element),
      kind: element instanceof HTMLSelectElement ? 'select' : (element instanceof HTMLTextAreaElement ? 'textarea' : element.type || 'text'),
      value: String(element.value || ''),
      placeholder: String(element.placeholder || ''),
      required: !!element.required,
      options: element instanceof HTMLSelectElement ? [...element.options].map(option => String(option.value)) : []
    }));
  return {title: document.title, url: location.href, fields};
})()
"""


_FORM_APPLY_SCRIPT = r"""
(() => {
  const assignments = __OPENWAND_ASSIGNMENTS__;
  const changed = [];
  const setValue = (element, value) => {
    const proto = element instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : element instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (!setter) throw new Error('field has no native value setter');
    setter.call(element, value);
    element.dispatchEvent(new InputEvent('input', {bubbles: true, composed: true, data: value, inputType: 'insertText'}));
    element.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
  };
  try {
    for (const assignment of assignments) {
      const element = document.querySelector(assignment.selector);
      if (!element) throw new Error(`field disappeared: ${assignment.selector}`);
      if (String(element.value || '') !== assignment.expected) throw new Error(`field changed: ${assignment.selector}`);
      changed.push({element, selector: assignment.selector, before: String(element.value || '')});
      setValue(element, assignment.value);
      if (String(element.value || '') !== assignment.value) throw new Error(`field rejected value: ${assignment.selector}`);
    }
    return {ok: true, verified: changed.length};
  } catch (error) {
    const rollbackErrors = [];
    for (const item of changed.reverse()) {
      try { setValue(item.element, item.before); }
      catch (rollbackError) { rollbackErrors.push(String(rollbackError)); }
    }
    return {ok: false, error: String(error), rolledBack: rollbackErrors.length === 0, rollbackErrors};
  }
})()
"""
