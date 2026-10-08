from __future__ import annotations

from pathlib import Path

import pytest

from thebigdiffer.context import (
    ApplicationContext,
    application_context_record,
    render_application_context,
)
from thebigdiffer.patch import build_patch_presentation, render_primary_input
from thebigdiffer.source import SourceRepository


def _source_repository(before: Path, after: Path) -> SourceRepository:
    return SourceRepository(
        before,
        after,
        max_lines_per_response=200,
        max_retrieved_bytes=128 * 1024,
        search_max_matches=20,
        search_context_lines=2,
    )


def test_application_context_rendering_and_record_are_exact() -> None:
    context = ApplicationContext(
        repository_type="Python web application framework",
        application_context="This subtree implements database and ORM facilities.",
        deployment_context="Unknown.",
        provenance="explicitly supplied by the user",
    )

    assert context.exact_text() == (
        "Repository type:\nPython web application framework\n\n"
        "Application context:\nThis subtree implements database and ORM facilities.\n\n"
        "Deployment context:\nUnknown.\n"
    )
    rendered = render_application_context(context)
    assert rendered.startswith("<application_context supplied='true'")
    assert context.exact_text() in rendered
    assert "does not establish installation" in rendered
    record = application_context_record(context)
    assert record["exact_text"] == context.exact_text()
    assert record["sha256"] == context.sha256
    assert record["deployment_context_established"] is False


def test_patch_and_primary_input_preserve_exact_source(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before.joinpath("sample.py").write_text(
        "TOKEN = 'old'\n\ndef render(value):\n    return TOKEN + value\n",
        encoding="utf-8",
    )
    after.joinpath("sample.py").write_text(
        "TOKEN = 'new'\n\ndef render(value):\n    return TOKEN + value\n",
        encoding="utf-8",
    )
    before.joinpath("removed.txt").write_text("gone\n", encoding="utf-8")
    after.joinpath("added.txt").write_text("new\n", encoding="utf-8")

    patch = build_patch_presentation(_source_repository(before, after), 256 * 1024)

    assert patch.changed_paths == ("added.txt", "removed.txt", "sample.py")
    assert "-TOKEN = 'old'" in patch.text
    assert "+TOKEN = 'new'" in patch.text
    assert "-gone" in patch.text
    assert "+new" in patch.text
    assert patch.omitted_records == ()
    assert all(record["status"] == "included" for record in patch.patch_records)

    context = ApplicationContext(
        repository_type="Python package",
        application_context="This repository implements a Python package.",
        deployment_context="Unknown.",
    )
    primary = render_primary_input(context, patch)
    assert render_application_context(context) in primary
    assert patch.text in primary


def test_patch_omission_is_explicit(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    before.joinpath("large.py").write_text("value = '" + "a" * 500 + "'\n", encoding="utf-8")
    after.joinpath("large.py").write_text("value = '" + "b" * 500 + "'\n", encoding="utf-8")

    patch = build_patch_presentation(_source_repository(before, after), 1)

    assert patch.changed_paths == ("large.py",)
    assert patch.omitted_records
    assert patch.patch_records[0]["status"] == "omitted_due_to_initial_evidence_budget"
    assert "<omitted_exact_patch>" in patch.text


@pytest.mark.parametrize("field", ["repository_type", "application_context", "deployment_context"])
def test_application_context_rejects_missing_factual_fields(field: str) -> None:
    values = {
        "repository_type": "Python package",
        "application_context": "Package context.",
        "deployment_context": "Unknown.",
    }
    values[field] = " "
    with pytest.raises(ValueError, match="must be non-empty text"):
        ApplicationContext(**values)
