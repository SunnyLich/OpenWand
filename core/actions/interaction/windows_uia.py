"""Windows UI Automation backend that never injects mouse or keyboard input."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from core.actions.interaction.contracts import (
    ApplicationIdentity,
    Bounds,
    ElementLocator,
    OperationType,
    SemanticOperation,
    WindowIdentity,
)
from core.actions.interaction.driver import (
    AmbiguousElementError,
    ElementNotFoundError,
    StaleElementError,
    TransportKind,
    UnsupportedOperationError,
)

_TREE_SCOPE_DESCENDANTS = 0x4
_PATTERN_VALUE = 10002
_PATTERN_SELECTION_ITEM = 10010
_PATTERN_TOGGLE = 10015

_CONTROL_TYPES = {
    50000: "button",
    50002: "checkbox",
    50003: "combo_box",
    50004: "edit",
    50007: "list_item",
    50008: "list",
    50011: "menu_item",
    50013: "radio_button",
    50018: "tab",
    50019: "tab_item",
    50020: "text",
    50023: "tree",
    50024: "tree_item",
    50025: "custom",
    50026: "group",
    50030: "document",
    50032: "window",
    50033: "pane",
}


class WindowsUIAutomationBackend:
    """Semantic Windows operations through UIA patterns, without focus or input injection."""

    transport = TransportKind.ACCESSIBILITY

    def __init__(
        self,
        *,
        uia: Any | None = None,
        uiac: Any | None = None,
        mutation_process_ids: frozenset[int] | set[int] = frozenset(),
    ) -> None:
        self._uia = uia
        self._uiac = uiac
        self._load_attempted = uia is not None
        self._validate_native_handles = uia is None
        self._mutation_process_ids = frozenset(int(value) for value in mutation_process_ids if int(value) > 0)

    def available(self) -> bool:
        self._load()
        return self._uia is not None

    @staticmethod
    def supports(operation_type: OperationType) -> bool:
        # Invoke needs a workflow-specific observable postcondition, and UIA
        # scrolling reports percentages rather than our bounded semantic units.
        return operation_type in {
            OperationType.INSPECT,
            OperationType.SET_VALUE,
            OperationType.TOGGLE,
            OperationType.SELECT,
        }

    def can_perform(self, element: Any, operation_type: OperationType) -> bool:
        if operation_type is OperationType.INSPECT:
            return True
        process_id = int(self._safe(lambda: element.CurrentProcessId, 0) or 0)
        if process_id not in self._mutation_process_ids:
            return False
        pattern_id = self._pattern_id(operation_type)
        if pattern_id is None or self._pattern(element, pattern_id) is None:
            return False
        if operation_type is OperationType.SET_VALUE:
            pattern = self._pattern(element, _PATTERN_VALUE)
            if pattern is None:
                return False
            return not bool(self._safe(lambda: pattern.CurrentIsReadOnly, True))
        return True

    def resolve(self, locator: ElementLocator) -> Any:
        root = self._window_root(locator)
        elements = self._descendants(root, limit=2500, include_root=True)
        matches = [element for element in elements if self._matches(element, root, locator)]
        if not matches:
            raise ElementNotFoundError("The recorded Windows accessibility element no longer exists.")
        if len(matches) > 1:
            raise AmbiguousElementError(
                "The Windows accessibility locator matched more than one element; Wisp refused to guess."
            )
        element = matches[0]
        if self._fingerprint(element, root, locator) != locator.snapshot_fingerprint:
            raise StaleElementError("The Windows accessibility element identity changed after the preview.")
        return element

    def read_state(self, element: Any) -> dict[str, Any]:
        sensitive = bool(self._safe(lambda: element.CurrentIsPassword, False))
        state: dict[str, Any] = {
            "enabled": bool(self._safe(lambda: element.CurrentIsEnabled, False)),
            "sensitive": sensitive,
            "value": "",
            "toggled": False,
            "selected": False,
            "scroll_offset": 0,
            "invocation_count": 0,
        }
        value_pattern = self._pattern(element, _PATTERN_VALUE)
        if value_pattern is not None and not sensitive:
            state["value"] = str(self._safe(lambda: value_pattern.CurrentValue, "") or "")
        toggle_pattern = self._pattern(element, _PATTERN_TOGGLE)
        if toggle_pattern is not None:
            state["toggled"] = int(self._safe(lambda: toggle_pattern.CurrentToggleState, 0) or 0) == 1
        selection_pattern = self._pattern(element, _PATTERN_SELECTION_ITEM)
        if selection_pattern is not None:
            state["selected"] = bool(self._safe(lambda: selection_pattern.CurrentIsSelected, False))
        return state

    def perform(self, operation: SemanticOperation, element: Any) -> dict[str, Any]:
        if operation.type is OperationType.SET_VALUE:
            pattern = self._required_pattern(element, _PATTERN_VALUE, operation.type)
            if bool(self._safe(lambda: pattern.CurrentIsReadOnly, True)):
                raise UnsupportedOperationError("The Windows accessibility value is read-only.")
            pattern.SetValue(operation.args["value"])
            return {"semantic_method": "ValuePattern.SetValue"}

        if operation.type is OperationType.TOGGLE:
            pattern = self._required_pattern(element, _PATTERN_TOGGLE, operation.type)
            expected = bool(operation.args["state"])
            for _attempt in range(3):
                current = int(self._safe(lambda: pattern.CurrentToggleState, 0) or 0) == 1
                if current == expected:
                    return {"semantic_method": "TogglePattern.Toggle", "already_set": True}
                pattern.Toggle()
            raise UnsupportedOperationError("The Windows toggle did not reach the exact requested state.")

        if operation.type is OperationType.SELECT:
            pattern = self._required_pattern(element, _PATTERN_SELECTION_ITEM, operation.type)
            pattern.Select()
            return {"semantic_method": "SelectionItemPattern.Select"}

        raise UnsupportedOperationError(f"Windows UI Automation does not safely support {operation.type.value}.")

    def inspect(
        self,
        locator: ElementLocator,
        *,
        max_depth: int,
        max_nodes: int,
    ) -> tuple[dict[str, Any], ...]:
        root = self.resolve(locator)
        root_window = self._window_root(locator)
        root_path = self._ancestor_path(root, root_window)
        snapshots: list[dict[str, Any]] = []
        for element in self._descendants(root, limit=max_nodes * 4, include_root=True):
            path = self._ancestor_path(element, root_window)
            if len(path) - len(root_path) > max_depth:
                continue
            try:
                snapshots.append(self._snapshot(element, root_window, locator.application, locator.window))
            except ValueError:
                continue
            if len(snapshots) >= max_nodes:
                break
        return tuple(snapshots)

    def inspect_window(
        self,
        window_id: int,
        *,
        max_depth: int = 6,
        max_nodes: int = 250,
    ) -> tuple[dict[str, Any], ...]:
        """Read one exact HWND without activating it or changing keyboard focus."""
        root = self._element_from_handle(window_id)
        process_id = int(self._safe(lambda: root.CurrentProcessId, 0) or 0)
        executable = self._process_executable(process_id)
        application = ApplicationIdentity(
            app_id=Path(executable).name.casefold() if executable else f"pid:{process_id}",
            process_id=process_id,
            executable=executable,
        )
        window = WindowIdentity(str(window_id), str(self._safe(lambda: root.CurrentName, "") or ""))
        snapshots: list[dict[str, Any]] = []
        for element in self._descendants(root, limit=max_nodes * 4, include_root=True):
            if len(self._ancestor_path(element, root)) > max_depth:
                continue
            try:
                snapshots.append(self._snapshot(element, root, application, window))
            except ValueError:
                continue
            if len(snapshots) >= max_nodes:
                break
        return tuple(snapshots)

    def _snapshot(
        self,
        element: Any,
        root: Any,
        application: ApplicationIdentity,
        window: WindowIdentity,
    ) -> dict[str, Any]:
        role = self._role(element)
        name = str(self._safe(lambda: element.CurrentName, "") or "")
        automation_id = str(self._safe(lambda: element.CurrentAutomationId, "") or "")
        bounds = self._bounds(element)
        locator = ElementLocator(
            application=application,
            window=window,
            role=role,
            accessible_name=name,
            automation_id=automation_id,
            ancestor_path=self._ancestor_path(element, root),
            snapshot_fingerprint=self._fingerprint_parts(element, root, window.window_id),
            bounds=bounds,
        )
        state = self.read_state(element)
        capabilities = tuple(
            operation.value
            for operation in (
                OperationType.INSPECT,
                OperationType.SET_VALUE,
                OperationType.TOGGLE,
                OperationType.SELECT,
            )
            if self.can_perform(element, operation)
        )
        return {
            "role": role,
            "name": name,
            "automation_id": automation_id,
            "ancestor_path": locator.ancestor_path,
            "bounds": bounds.to_dict(),
            "value": "<redacted>" if role == "edit" or state["sensitive"] else state["value"],
            "enabled": state["enabled"],
            "sensitive": state["sensitive"],
            "capabilities": capabilities,
            "locator": locator,
        }

    def _window_root(self, locator: ElementLocator) -> Any:
        try:
            window_id = int(locator.window.window_id)
        except ValueError as exc:
            raise ElementNotFoundError("The recorded Windows window identifier is invalid.") from exc
        root = self._element_from_handle(window_id)
        process_id = int(self._safe(lambda: root.CurrentProcessId, 0) or 0)
        if locator.application.process_id and process_id != locator.application.process_id:
            raise StaleElementError("The recorded window now belongs to a different process.")
        if locator.application.executable:
            executable = self._process_executable(process_id)
            if not executable or os.path.normcase(executable) != os.path.normcase(locator.application.executable):
                raise StaleElementError("The recorded window now belongs to a different application executable.")
        if locator.window.title:
            title = str(self._safe(lambda: root.CurrentName, "") or "")
            if title != locator.window.title:
                raise StaleElementError("The recorded Windows window title changed after preview.")
        return root

    def _element_from_handle(self, window_id: int) -> Any:
        self._load()
        if self._uia is None:
            raise ElementNotFoundError("Windows UI Automation is unavailable.")
        if sys.platform == "win32" and self._validate_native_handles:
            import ctypes

            if not window_id or not ctypes.windll.user32.IsWindow(window_id):
                raise ElementNotFoundError("The recorded Windows window is no longer open.")
        root = self._safe(lambda: self._uia.ElementFromHandle(window_id), None)
        if root is None:
            raise ElementNotFoundError("Windows could not inspect the recorded window.")
        return root

    def _matches(self, element: Any, root: Any, locator: ElementLocator) -> bool:
        return (
            self._role(element) == locator.role
            and (not locator.accessible_name or self._safe(lambda: element.CurrentName, "") == locator.accessible_name)
            and (not locator.automation_id or self._safe(lambda: element.CurrentAutomationId, "") == locator.automation_id)
            and self._ancestor_path(element, root) == locator.ancestor_path
        )

    def _fingerprint(self, element: Any, root: Any, locator: ElementLocator) -> str:
        return self._fingerprint_parts(element, root, locator.window.window_id)

    def _fingerprint_parts(self, element: Any, root: Any, window_id: str) -> str:
        runtime_id = self._safe(lambda: tuple(element.GetRuntimeId()), ())
        payload = {
            "window_id": window_id,
            "process_id": int(self._safe(lambda: element.CurrentProcessId, 0) or 0),
            "runtime_id": runtime_id,
            "control_type": int(self._safe(lambda: element.CurrentControlType, 0) or 0),
            "name": str(self._safe(lambda: element.CurrentName, "") or ""),
            "automation_id": str(self._safe(lambda: element.CurrentAutomationId, "") or ""),
            "ancestor_path": self._ancestor_path(element, root),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _ancestor_path(self, element: Any, root: Any) -> tuple[str, ...]:
        if element is root:
            return ()
        self._load()
        uia = self._uia
        if uia is None:
            return ()
        walker = self._safe(lambda: uia.ControlViewWalker, None)
        if walker is None:
            return ()
        parts: list[str] = []
        current = element
        for _depth in range(24):
            parent = self._safe(lambda current=current: walker.GetParentElement(current), None)
            if parent is None or parent is root:
                break
            role = self._role(parent)
            name = str(self._safe(lambda parent=parent: parent.CurrentName, "") or "")
            parts.append(f"{role}:{name}")
            current = parent
        parts.reverse()
        return tuple(parts)

    def _descendants(self, root: Any, *, limit: int, include_root: bool) -> tuple[Any, ...]:
        self._load()
        uia = self._uia
        if uia is None:
            return (root,) if include_root else ()
        items: list[Any] = [root] if include_root else []
        condition = uia.CreateTrueCondition()
        collection = root.FindAll(_TREE_SCOPE_DESCENDANTS, condition)
        length = min(int(self._safe(lambda: collection.Length, 0) or 0), max(0, limit - len(items)))
        for index in range(length):
            element = self._safe(lambda index=index: collection.GetElement(index), None)
            if element is not None:
                items.append(element)
        return tuple(items)

    def _pattern(self, element: Any, pattern_id: int) -> Any | None:
        raw = self._safe(lambda: element.GetCurrentPattern(pattern_id), None)
        if raw is None:
            return None
        interface_name = {
            _PATTERN_VALUE: "IUIAutomationValuePattern",
            _PATTERN_TOGGLE: "IUIAutomationTogglePattern",
            _PATTERN_SELECTION_ITEM: "IUIAutomationSelectionItemPattern",
        }.get(pattern_id, "")
        interface = getattr(self._uiac, interface_name, None) if self._uiac is not None else None
        if interface is None or not hasattr(raw, "QueryInterface"):
            return raw
        return self._safe(lambda: raw.QueryInterface(interface), None)

    def _required_pattern(self, element: Any, pattern_id: int, operation_type: OperationType) -> Any:
        pattern = self._pattern(element, pattern_id)
        if pattern is None:
            raise UnsupportedOperationError(f"The target does not expose {operation_type.value} through UIA.")
        return pattern

    @staticmethod
    def _pattern_id(operation_type: OperationType) -> int | None:
        return {
            OperationType.SET_VALUE: _PATTERN_VALUE,
            OperationType.TOGGLE: _PATTERN_TOGGLE,
            OperationType.SELECT: _PATTERN_SELECTION_ITEM,
        }.get(operation_type)

    @staticmethod
    def _role(element: Any) -> str:
        control_type = int(WindowsUIAutomationBackend._safe(lambda: element.CurrentControlType, 0) or 0)
        return _CONTROL_TYPES.get(control_type, f"control_{control_type}")

    @staticmethod
    def _bounds(element: Any) -> Bounds:
        rect = WindowsUIAutomationBackend._safe(lambda: element.CurrentBoundingRectangle, None)
        if rect is None:
            return Bounds(0, 0, 0, 0)
        try:
            left = int(rect.left)
            top = int(rect.top)
            right = int(rect.right)
            bottom = int(rect.bottom)
        except (AttributeError, TypeError, ValueError):
            try:
                left, top, right, bottom = (int(value) for value in rect)
            except (TypeError, ValueError):
                return Bounds(0, 0, 0, 0)
        return Bounds(left, top, max(0, right - left), max(0, bottom - top))

    @staticmethod
    def _process_executable(process_id: int) -> str:
        if not process_id:
            return ""
        try:
            import psutil

            return str(psutil.Process(process_id).exe() or "")
        except Exception:
            return ""

    def _load(self) -> None:
        if self._load_attempted:
            return
        self._load_attempted = True
        if sys.platform != "win32":
            return
        try:
            import comtypes.client

            comtypes.client.GetModule("UIAutomationCore.dll")
            import comtypes.gen.UIAutomationClient as uiac  # type: ignore[import-not-found]

            self._uiac = uiac
            self._uia = comtypes.client.CreateObject(
                "{ff48dba4-60ef-4201-aa87-54103eef594e}",
                interface=uiac.IUIAutomation,
            )
        except Exception:
            self._uia = None
            self._uiac = None

    @staticmethod
    def _safe(callback, fallback):
        try:
            return callback()
        except Exception:
            return fallback


__all__ = ["WindowsUIAutomationBackend"]
