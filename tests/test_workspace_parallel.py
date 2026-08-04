"""Tests for conservative Virtual Workspace task splitting."""
from __future__ import annotations

import pytest

from core.agent.workspace_parallel import split_independent_workspace_objective


def test_splits_numbered_and_bulleted_distinct_file_tasks() -> None:
    result = split_independent_workspace_objective(
        "1. Create pages/home.html with a welcome heading\n"
        "2) Write `styles/theme.css` with a dark palette\n"
        "- Generate notes/readme.md with three short paragraphs"
    )

    assert result is not None
    assert [item.target_path for item in result] == [
        "pages/home.html",
        "styles/theme.css",
        "notes/readme.md",
    ]
    assert result[0].objective == "Create pages/home.html with a welcome heading"


@pytest.mark.parametrize(
    "objective",
    [
        "Create a.txt\nCreate b.txt",
        "- Create a.txt",
        "- Create a.txt\n- Create b.txt\n- Create c.txt\n- Create d.txt\n- Create e.txt\n- Create f.txt\n- Create g.txt",
        "Tasks:\n- Create a.txt\n- Create b.txt",
        "- Explain the plan for a.txt\n- Create b.txt",
    ],
)
def test_rejects_non_checklists_wrong_counts_and_ambiguous_actions(objective: str) -> None:
    assert split_independent_workspace_objective(objective) is None


@pytest.mark.parametrize(
    "phrase",
    [
        "after a.txt is complete",
        "then summarize it",
        "depends on the other task",
        "using the output from the model",
        "based on earlier work",
        "finally add a heading",
        "when the first task is done",
    ],
)
def test_rejects_dependency_language(phrase: str) -> None:
    objective = f"- Create a.txt {phrase}\n- Create b.txt independently"
    assert split_independent_workspace_objective(objective) is None


@pytest.mark.parametrize(
    "objective",
    [
        "- Create a.txt\n- Edit A.txt",
        "- Create a.txt and mention b.txt\n- Create c.txt",
        "- Create a.txt and write a heading\n- Create b.txt",
        "- Create a.txt; delete it\n- Create b.txt",
    ],
)
def test_rejects_duplicates_multiple_files_and_compound_actions(objective: str) -> None:
    assert split_independent_workspace_objective(objective) is None


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape.txt",
        "/absolute.txt",
        "C:/host.txt",
        "notes/../../escape.txt",
        r"notes\\windows.txt",
        "CON.txt",
        ".env",
    ],
)
def test_rejects_unsafe_or_non_explicit_filename_targets(unsafe: str) -> None:
    objective = f"- Create `{unsafe}` with safe text\n- Create okay.txt with safe text"
    assert split_independent_workspace_objective(objective) is None


def test_rejects_filename_like_references_even_when_target_is_clear() -> None:
    assert (
        split_independent_workspace_objective(
            "- Create index.html with a reference to app.js\n"
            "- Create styles.css with basic colors"
        )
        is None
    )
