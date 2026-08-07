"""LibreOffice Calc selection and action integration."""

from core.actions.adapters.calc.adapter import CalcActionAdapter, action_plan_from_dict
from core.actions.adapters.calc.advanced import calc_advanced_capabilities
from core.actions.adapters.calc.plans import (
    build_chart_plan,
    build_cleanup_plan,
    build_format_table_plan,
    build_sort_range_plan,
)
from core.actions.adapters.calc.preview import render_calc_preview
from core.actions.adapters.calc.reader import CalcSelectionReader, is_calc_app
from core.actions.adapters.calc.snapshot import CalcSnapshot

__all__ = [
    "CalcActionAdapter",
    "CalcSelectionReader",
    "CalcSnapshot",
    "action_plan_from_dict",
    "build_chart_plan",
    "build_cleanup_plan",
    "build_format_table_plan",
    "build_sort_range_plan",
    "is_calc_app",
    "render_calc_preview",
    "calc_advanced_capabilities",
]
