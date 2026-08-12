"""Traceability checks between the function inventory and explicit test relations."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts import workflow_manifest
from scripts.generate_workflow_manifest import build_manifest, load_relations
from scripts.workflow_manifest import load_inventory, load_manifest, validate_manifest

pytestmark = pytest.mark.workflow

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "docs" / "APP_FUNCTION_INVENTORY.md"
MANIFEST = ROOT / "tests" / "workflows" / "manifest.json"
RELATIONS = ROOT / "tests" / "workflows" / "function_test_relations.json"


def test_inventory_parser_preserves_every_function_and_failure_reference():
    functions = load_inventory(INVENTORY)

    assert len(functions) == 472
    assert sum(len(item.failure_refs) for item in functions) == 3296
    assert functions[0].function_id == "F001"
    assert functions[-1].function_id == "F472"
    assert len({item.name for item in functions}) == len(functions)


def test_manifest_reports_confirmed_relationships_and_unresolved_functions():
    summary = validate_manifest(root=ROOT, manifest_path=MANIFEST)

    assert summary["inventory_functions"] == 472
    assert summary["failure_references"] == 3296
    assert summary["recorded_functions"] == 472
    assert summary["confirmed_functions"] == 12
    assert summary["relationship_count"] == 18
    assert len(summary["unresolved_functions"]) == 460
    assert summary["enforce_complete"] is True


def test_explicit_relations_are_many_to_many_without_duplicates():
    relations = load_relations(RELATIONS)

    assert len(relations["F030"]) == 2
    shared_node = (
        "tests/runtime/test_supervisor_ipc.py::"
        "test_openwand_supervisor_starts_real_app_worker_process_set"
    )
    assert shared_node in relations["F016"]
    assert shared_node in relations["F030"]
    assert all(len(nodes) == len(set(nodes)) for nodes in relations.values())


def test_manifest_is_reproducible_only_from_inventory_and_explicit_relations():
    generated = build_manifest(ROOT, RELATIONS)

    assert generated == load_manifest(MANIFEST)


def test_adding_an_unrelated_test_cannot_change_the_manifest(tmp_path):
    expected = build_manifest(ROOT, RELATIONS)
    inventory_copy = tmp_path / "docs" / "APP_FUNCTION_INVENTORY.md"
    relations_copy = tmp_path / "tests" / "workflows" / RELATIONS.name
    unrelated_test = tmp_path / "tests" / "test_unrelated_new_feature.py"
    inventory_copy.parent.mkdir(parents=True)
    relations_copy.parent.mkdir(parents=True)
    shutil.copy2(INVENTORY, inventory_copy)
    shutil.copy2(RELATIONS, relations_copy)
    unrelated_test.write_text(
        "def test_better_named_but_unrelated():\n    assert True\n",
        encoding="utf-8",
    )

    assert build_manifest(tmp_path, relations_copy) == expected


def test_broken_relation_names_the_function_and_missing_node(tmp_path):
    manifest = build_manifest(ROOT, RELATIONS)
    manifest["workflows"][4]["related_test_node_ids"] = [
        "tests/test_profile_user_workflows.py::test_this_relation_was_renamed"
    ]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(
        AssertionError,
        match="missing test function in relation F005: .*test_this_relation_was_renamed",
    ):
        validate_manifest(root=ROOT, manifest_path=path)


def test_duplicate_relation_is_rejected_at_the_explicit_source(tmp_path):
    node_id = "tests/test_profile_user_workflows.py::test_example"
    path = tmp_path / "relations.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "relations": {"F005": [node_id, node_id]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="relations for F005 contain a duplicate"):
        load_relations(path)


def test_unknown_function_relation_is_rejected(tmp_path):
    path = tmp_path / "relations.json"
    path.write_text(
        json.dumps({"schema_version": 1, "relations": {"F999": []}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown function IDs: F999"):
        build_manifest(ROOT, path)


def test_related_test_must_remain_scheduled(monkeypatch, tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(build_manifest(ROOT, RELATIONS)), encoding="utf-8")
    real_load = workflow_manifest.load_manifest

    def load_with_unscheduled_relation(source_path: Path):
        data = real_load(source_path)
        if source_path.name == "test_map.json":
            for entry in data["entries"]:
                if entry["path"] == "tests/test_profile_user_workflows.py":
                    entry["schedule"] = ""
        return data

    monkeypatch.setattr(workflow_manifest, "load_manifest", load_with_unscheduled_relation)
    with pytest.raises(
        AssertionError,
        match="related test is unscheduled F005",
    ):
        validate_manifest(root=ROOT, manifest_path=path)
