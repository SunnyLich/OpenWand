"""Action files: one action is one Python file in a folder.

See private/ACTION_FILES_PLAN.md for the agreed design.
"""

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
from core.action_files.loader import load_catalog, lookup_report
from core.action_files.parse import parse_action_file

__all__ = [
    "ACCESS_COLOUR",
    "ACCESS_SEVERITY",
    "CONTEXT_SOURCES",
    "Access",
    "ActionCatalog",
    "ActionFile",
    "AppDef",
    "AppMatch",
    "BoundAction",
    "CallerDef",
    "LoadIssue",
    "load_catalog",
    "lookup_report",
    "parse_action_file",
]
