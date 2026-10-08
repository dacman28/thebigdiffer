from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

from thebigdiffer.context import ApplicationContext
from thebigdiffer.investigator import ClaudeInvestigator


class _Provider:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.requests.append(request)
        return {
            "stopReason": "end_turn",
            "usage": {"inputTokens": 100, "outputTokens": 20},
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Qualified report from the available source."},
                    ],
                }
            },
        }


def _entry(root: Path, kind: str | None, value: str, outside: Path) -> str | None:
    path = root / "entry.dat"
    if kind is None:
        return None
    if kind == "binary":
        payload = b"\x00\xffPRIVATE_BINARY_" + value.encode()
        path.write_bytes(payload)
    elif kind == "symlink":
        target = outside / value
        target.write_text("PRIVATE_SYMLINK_TARGET_CONTENT", encoding="utf-8")
        os.symlink(target, path)
        payload = os.fsencode(target)
    else:
        payload = f"PRIVATE_TRANSITION_TEXT_{value}\n".encode()
        path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "old_kind,new_kind,changed",
    [
        pytest.param(None, "binary", True, id="added-binary"),
        pytest.param("binary", None, True, id="removed-binary"),
        pytest.param("binary", "binary", True, id="modified-binary"),
        pytest.param("binary", "text", True, id="binary-to-text"),
        pytest.param("text", "binary", True, id="text-to-binary"),
        pytest.param(None, "symlink", True, id="added-symlink"),
        pytest.param("symlink", None, True, id="removed-symlink"),
        pytest.param("symlink", "symlink", True, id="changed-symlink"),
        pytest.param("binary", "binary", False, id="unchanged-binary"),
        pytest.param("symlink", "symlink", False, id="unchanged-symlink"),
    ],
)
@pytest.mark.parametrize("with_text_change", [False, True], ids=["non-text-only", "mixed-text"])
def test_non_text_entries_preserve_representation_and_allow_investigation(
    tmp_path: Path,
    old_kind: str | None,
    new_kind: str | None,
    changed: bool,
    with_text_change: bool,
) -> None:
    before, after, outside = (tmp_path / name for name in ("before", "after", "outside"))
    for directory in (before, after, outside):
        directory.mkdir()
    before_sha = _entry(before, old_kind, "before", outside)
    after_sha = _entry(after, new_kind, "after" if changed else "before", outside)
    if with_text_change:
        before.joinpath("app.py").write_text("value = 1\n", encoding="utf-8")
        after.joinpath("app.py").write_text("value = 2\n", encoding="utf-8")
    provider = _Provider()
    output = tmp_path / "output"
    report = ClaudeInvestigator(
        before_root=before,
        after_root=after,
        output_dir=output,
        application_context=ApplicationContext("Fictitious package", "Test only.", "Unknown."),
        provider=provider,
    ).investigate()

    assert report.stop_reason == "model_end_turn"
    assert len(provider.requests) == 1
    assert output.joinpath("research-report.md").is_file()
    assert report.patch.omitted_records == ()
    expected_paths = (["app.py"] if with_text_change else []) + (["entry.dat"] if changed else [])
    assert list(report.patch.changed_paths) == expected_paths
    non_text = [item for item in report.patch.patch_records if item["status"] == "non_text"]
    if changed:
        expected = {
            "path": "entry.dat",
            "status": "non_text",
            "before_sha256": before_sha,
            "after_sha256": after_sha,
            "retrieval": "source tools do not return binary content",
        }
        assert non_text == [expected]
        assert f"\n<non_text_change>\n{expected}\n</non_text_change>\n" in report.patch.text
    else:
        assert non_text == []
        assert "<non_text_change>" not in report.patch.text
    if with_text_change:
        assert "-value = 1\n+value = 2\n" in report.patch.text
    request_text = json.dumps(provider.requests)
    for forbidden in (
        "PRIVATE_BINARY",
        "PRIVATE_SYMLINK_TARGET_CONTENT",
        "PRIVATE_TRANSITION_TEXT",
        str(outside),
    ):
        assert forbidden not in request_text
