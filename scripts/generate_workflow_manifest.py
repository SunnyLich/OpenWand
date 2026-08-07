"""Generate factual function/test traceability from explicit relations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    from scripts.workflow_manifest import load_inventory, load_manifest
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from workflow_manifest import load_inventory, load_manifest


RELATIONS_RELATIVE = Path("tests/workflows/function_test_relations.json")


def load_relations(path: Path) -> dict[str, list[str]]:
    """Load explicitly reviewed many-to-many function/test relationships."""

    data = load_manifest(path)
    if data.get("schema_version") != 1:
        raise ValueError("function/test relation schema_version must be 1")
    raw_relations = data.get("relations")
    if not isinstance(raw_relations, dict):
        raise ValueError("function/test relations must be a JSON object")
    relations: dict[str, list[str]] = {}
    for function_id, raw_nodes in raw_relations.items():
        if not isinstance(raw_nodes, list):
            raise ValueError(f"relations for {function_id} must be a list")
        nodes = [str(node_id) for node_id in raw_nodes]
        if any(not node_id.strip() for node_id in nodes):
            raise ValueError(f"relations for {function_id} contain an empty node ID")
        if len(nodes) != len(set(nodes)):
            raise ValueError(f"relations for {function_id} contain a duplicate node ID")
        relations[str(function_id)] = nodes
    return relations


def build_manifest(
    root: Path,
    relations_path: Path | None = None,
) -> dict[str, Any]:
    """Copy inventory facts and explicitly reviewed relationships into a manifest."""

    inventory = load_inventory(root / "docs" / "APP_FUNCTION_INVENTORY.md")
    inventory_ids = {item.function_id for item in inventory}
    source_path = relations_path or root / RELATIONS_RELATIVE
    relations = load_relations(source_path)
    unknown_ids = sorted(set(relations) - inventory_ids)
    if unknown_ids:
        raise ValueError(
            "function/test relations contain unknown function IDs: "
            + ", ".join(unknown_ids)
        )
    records = [
        {
            "function_id": item.function_id,
            "function": item.name,
            "failure_refs": list(item.failure_refs),
            "related_test_node_ids": list(relations.get(item.function_id, [])),
        }
        for item in inventory
    ]
    return {
        "schema_version": 3,
        "inventory_source": "docs/APP_FUNCTION_INVENTORY.md",
        "relation_source": RELATIONS_RELATIVE.as_posix(),
        "enforce_complete": True,
        "workflows": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    path = root / "tests" / "workflows" / "manifest.json"
    generated = json.dumps(build_manifest(root), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        return 0 if path.read_text(encoding="utf-8") == generated else 1
    path.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
