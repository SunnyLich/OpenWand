"""Load and validate explicit function/test traceability records."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

_INVENTORY_LINE = re.compile(
    r"^- \[[ xX]\] (?P<name>.+?) (?P<refs>(?:\[\d+\])+)$"
)
_REFERENCE = re.compile(r"\[(\d+)\]")


@dataclass(frozen=True)
class InventoryFunction:
    """One function and its function-specific failure references."""

    function_id: str
    name: str
    failure_refs: tuple[int, ...]


def load_inventory(path: Path) -> list[InventoryFunction]:
    """Read the authoritative inventory section before its audit catalogue."""

    functions: list[InventoryFunction] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line == "## Audit notes":
            break
        match = _INVENTORY_LINE.match(line)
        if match is None:
            continue
        refs = tuple(int(value) for value in _REFERENCE.findall(match.group("refs")))
        functions.append(
            InventoryFunction(
                function_id=f"F{len(functions) + 1:03d}",
                name=match.group("name"),
                failure_refs=refs,
            )
        )
    return functions


def load_manifest(path: Path) -> dict[str, Any]:
    """Read a JSON workflow artifact."""

    return json.loads(path.read_text(encoding="utf-8"))


@cache
def _test_node_suffixes(path: Path) -> set[str]:
    """Return top-level and class-qualified pytest node suffixes from an AST."""

    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    suffixes: set[str] = set()

    def visit(body: list[ast.stmt], parents: tuple[str, ...] = ()) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                visit(list(node.body), (*parents, node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("test_"):
                    suffixes.add("::".join((*parents, node.name)))

    visit(list(tree.body))
    return suffixes


def _node_exists(root: Path, node_id: str) -> tuple[bool, str]:
    parts = str(node_id).split("::")
    if len(parts) < 2:
        return False, "invalid test node ID"
    relative_path = parts[0].replace("\\", "/")
    test_path = root / relative_path
    if not test_path.is_file():
        return False, "missing test file"
    suffix = "::".join(part.split("[", 1)[0] for part in parts[1:])
    if suffix not in _test_node_suffixes(test_path):
        return False, "missing test function"
    return True, ""


def validate_manifest(*, root: Path, manifest_path: Path) -> dict[str, Any]:
    """Validate explicit relations and return honest traceability counts."""

    manifest = load_manifest(manifest_path)
    inventory_path = root / str(manifest["inventory_source"])
    inventory = load_inventory(inventory_path)
    by_id = {item.function_id: item for item in inventory}
    catalog = load_manifest(root / "tests" / "catalog" / "test_map.json")
    scheduled_files = {
        str(entry.get("path", "")).replace("\\", "/"): entry
        for entry in catalog.get("entries", [])
    }
    errors: list[str] = []
    seen: set[str] = set()
    unresolved: list[str] = []
    relationship_count = 0
    required_fields = {
        "function_id",
        "function",
        "failure_refs",
        "related_test_node_ids",
    }

    if manifest.get("schema_version") != 3:
        errors.append("schema_version must be 3")
    if manifest.get("relation_source") != "tests/workflows/function_test_relations.json":
        errors.append("relation_source must name the explicit function/test relation file")

    for index, record in enumerate(manifest.get("workflows", []), start=1):
        missing_fields = sorted(required_fields - set(record))
        if missing_fields:
            errors.append(f"record {index} missing fields: {', '.join(missing_fields)}")
            continue
        unexpected = sorted(set(record) - required_fields)
        if unexpected:
            errors.append(f"record {index} contains unexpected fields: {', '.join(unexpected)}")
        function_id = str(record["function_id"])
        item = by_id.get(function_id)
        if item is None:
            errors.append(f"unknown inventory function ID: {function_id}")
            continue
        if function_id in seen:
            errors.append(f"duplicate workflow record: {function_id}")
        seen.add(function_id)
        if record["function"] != item.name:
            errors.append(f"function name differs from inventory for {function_id}")
        if tuple(record["failure_refs"]) != item.failure_refs:
            errors.append(f"failure references differ from inventory for {function_id}")
        nodes = [str(node_id) for node_id in record["related_test_node_ids"]]
        if len(nodes) != len(set(nodes)):
            errors.append(f"duplicate related test for {function_id}")
        if not nodes:
            unresolved.append(function_id)
        relationship_count += len(nodes)
        for node_id in nodes:
            exists, reason = _node_exists(root, node_id)
            if not exists:
                errors.append(f"{reason} in relation {function_id}: {node_id}")
                continue
            test_path = node_id.split("::", 1)[0].replace("\\", "/")
            schedule = scheduled_files.get(test_path)
            if schedule is None:
                errors.append(f"related test is absent from the test catalogue {function_id}: {node_id}")
            elif not schedule.get("schedule"):
                errors.append(f"related test is unscheduled {function_id}: {node_id}")

    missing_ids = [item.function_id for item in inventory if item.function_id not in seen]
    if manifest.get("enforce_complete") and missing_ids:
        errors.append(f"{len(missing_ids)} inventory functions have no traceability record")
    if errors:
        raise AssertionError("Workflow manifest is invalid:\n- " + "\n- ".join(errors))
    return {
        "inventory_functions": len(inventory),
        "failure_references": sum(len(item.failure_refs) for item in inventory),
        "recorded_functions": len(seen),
        "confirmed_functions": len(seen) - len(unresolved),
        "unresolved_functions": unresolved,
        "relationship_count": relationship_count,
        "enforce_complete": bool(manifest.get("enforce_complete")),
    }
