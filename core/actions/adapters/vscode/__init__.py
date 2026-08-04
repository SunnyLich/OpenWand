"""Preview-first actions for VS Code and compatible editors."""

from core.actions.adapters.vscode.adapter import VSCodeActionAdapter, action_plan_from_dict
from core.actions.adapters.vscode.advanced import (
    build_format_document_plan,
    build_registered_task_plan,
    build_rename_symbol_plan,
    build_test_file_plan,
    render_vscode_extension_preview,
    validate_vscode_extension_plan,
    vscode_extension_capabilities,
)
from core.actions.adapters.vscode.devtools import VSCodeDevToolsAdapter, VSCodeDevToolsTarget
from core.actions.adapters.vscode.extension_api import VSCodeExtensionAPIAdapter, VSCodeExtensionEndpoint
from core.actions.adapters.vscode.plans import (
    build_replace_file_plan,
    build_replace_selection_plan,
)
from core.actions.adapters.vscode.preview import render_vscode_preview, render_vscode_untitled_preview
from core.actions.adapters.vscode.reader import VSCodeSelectionReader, is_vscode_app
from core.actions.adapters.vscode.snapshot import VSCodeSnapshot

__all__ = [
    "VSCodeActionAdapter",
    "VSCodeSelectionReader",
    "VSCodeSnapshot",
    "action_plan_from_dict",
    "build_replace_selection_plan",
    "build_replace_file_plan",
    "is_vscode_app",
    "render_vscode_preview",
    "render_vscode_untitled_preview",
    "VSCodeDevToolsAdapter",
    "VSCodeDevToolsTarget",
    "VSCodeExtensionAPIAdapter",
    "VSCodeExtensionEndpoint",
    "build_format_document_plan",
    "build_registered_task_plan",
    "build_rename_symbol_plan",
    "build_test_file_plan",
    "render_vscode_extension_preview",
    "validate_vscode_extension_plan",
    "vscode_extension_capabilities",
]
