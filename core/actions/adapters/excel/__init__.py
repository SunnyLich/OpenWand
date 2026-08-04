"""Windows Excel adapter backed by Excel's own object model."""

from core.actions.adapters.excel.adapter import ExcelActionAdapter
from core.actions.adapters.excel.advanced import excel_advanced_capabilities
from core.actions.adapters.excel.capabilities import excel_capabilities, excel_registry
from core.actions.adapters.excel.plans import build_table_chart_plan
from core.actions.adapters.excel.snapshot import ExcelSnapshot

__all__ = [
    "ExcelActionAdapter",
    "ExcelSnapshot",
    "build_table_chart_plan",
    "excel_capabilities",
    "excel_registry",
    "excel_advanced_capabilities",
]
