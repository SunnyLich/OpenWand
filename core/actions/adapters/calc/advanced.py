"""Advanced Calc contracts; execution requires an injected Calc application API."""

from core.actions.adapters.spreadsheet_advanced import *  # noqa: F403


def calc_advanced_capabilities():
    return spreadsheet_advanced_capabilities("libreoffice_calc")  # noqa: F405
