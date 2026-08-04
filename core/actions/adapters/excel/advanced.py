"""Advanced Excel contracts; execution requires an injected Excel application API."""

from core.actions.adapters.spreadsheet_advanced import *  # noqa: F403


def excel_advanced_capabilities():
    return spreadsheet_advanced_capabilities("excel")  # noqa: F405
