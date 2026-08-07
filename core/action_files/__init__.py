"""Action files: one action is one Python file in a folder.

See private/ACTION_FILES_PLAN.md for the agreed design.
"""

from core.action_files.addons import (
    ADDON_ACTION_KINDS,
    ADDON_ACTIONS_DIR,
    AddonActionFile,
    load_addon_actions,
    parse_addon_action_file,
)
from core.action_files.contracts import (
    ACCESS_COLOUR,
    ACCESS_SEVERITY,
    CONTEXT_SOURCES,
    Access,
    ActionCatalog,
    ActionFile,
    AppDef,
    AppMatch,
    BoundAction,
    CallerDef,
    LoadIssue,
)
from core.action_files.edit import save_callers, update_toml_values
from core.action_files.execution import ActionScriptResult, action_from_dict, run_action_script
from core.action_files.loader import load_catalog, lookup_report
from core.action_files.parse import parse_action_file
from core.action_files.store import (
    ActionCatalogStore,
    app_picker_context,
    caller_rows,
    configured_caller_rows,
    invalidate_live_catalog,
    live_catalog,
)

__all__ = [
    "ACCESS_COLOUR",
    "ACCESS_SEVERITY",
    "ADDON_ACTION_KINDS",
    "ADDON_ACTIONS_DIR",
    "CONTEXT_SOURCES",
    "Access",
    "AddonActionFile",
    "ActionCatalog",
    "ActionFile",
    "AppDef",
    "AppMatch",
    "BoundAction",
    "CallerDef",
    "LoadIssue",
    "load_catalog",
    "load_addon_actions",
    "lookup_report",
    "parse_action_file",
    "parse_addon_action_file",
    "ActionCatalogStore",
    "ActionScriptResult",
    "app_picker_context",
    "action_from_dict",
    "caller_rows",
    "configured_caller_rows",
    "invalidate_live_catalog",
    "live_catalog",
    "run_action_script",
    "save_callers",
    "update_toml_values",
]
