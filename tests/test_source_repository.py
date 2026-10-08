from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thebigdiffer.investigator.tool_contract import validate_bedrock_tool_config
from thebigdiffer.source import TOOL_CONFIG, SourceRepository


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    return before, after


def _repository(
    before: Path,
    after: Path,
    *,
    byte_limit: int = 65_536,
    matches: int = 20,
    lines: int = 200,
) -> SourceRepository:
    return SourceRepository(
        before,
        after,
        max_lines_per_response=lines,
        max_retrieved_bytes=byte_limit,
        search_max_matches=matches,
        search_context_lines=1,
    )


def test_tools_return_exact_provenance_search_and_definitions(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("sample.py").write_text("TOKEN = 'old'\n\ndef run():\n    return TOKEN\n")
    after.joinpath("sample.py").write_text("TOKEN = 'new'\n\ndef run():\n    return TOKEN\n")
    repository = _repository(before, after)

    read = repository.read_source("before", "sample.py", 1, 2)
    search = repository.search_source("after", "return TOKEN")
    definition = repository.find_definition("before", "TOKEN")

    assert read["source"] == "TOKEN = 'old'\n\n"
    assert read["provenance"]["start_line"] == 1
    assert len(read["provenance"]["file_sha256"]) == 64
    assert search["literal_search"] is True
    assert search["matches"][0]["line"] == 4
    assert search["matches"][0]["source"] == "def run():\n    return TOKEN\n"
    assert definition["resolution"] == "resolved"
    assert definition["definitions"][0]["source"] == "TOKEN = 'old'\n"


@pytest.mark.parametrize("path", ["../secret.py", "/tmp/secret.py", "a//b.py", "C:/x.py"])
def test_tools_reject_unsafe_paths(tmp_path: Path, path: str) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("safe.py").write_text("x = 1\n")
    after.joinpath("safe.py").write_text("x = 2\n")

    result = _repository(before, after).execute(
        "read_source", {"version": "before", "path": path, "start_line": 1, "end_line": 1}
    )

    assert result["ok"] is False
    assert "unsafe relative path" in result["error"]


def test_hash_change_is_detected_after_inventory(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("safe.py").write_text("x = 1\n")
    after.joinpath("safe.py").write_text("x = 2\n")
    repository = _repository(before, after)
    before.joinpath("safe.py").write_text("x = 9\n")

    result = repository.execute(
        "read_source",
        {"version": "before", "path": "safe.py", "start_line": 1, "end_line": 1},
    )

    assert result["ok"] is False
    assert "file changed after inventory" in result["error"]


def test_symlink_escape_is_not_returned(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("TOKEN = 'secret'\n")
    before.joinpath("escape.py").symlink_to(outside)
    after.joinpath("escape.py").symlink_to(outside)

    result = _repository(before, after).execute(
        "find_references",
        {"version": "before", "identifier": "TOKEN", "path": "escape.py"},
    )

    assert result["ok"] is False
    assert result["references"] == []
    assert "TOKEN = 'secret'" not in json.dumps(result)


def test_source_byte_limit_fails_without_partial_source_or_charge(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("safe.py").write_text("abcdef\n")
    after.joinpath("safe.py").write_text("abcdef\n")
    repository = _repository(before, after, byte_limit=3)

    result = repository.execute(
        "read_source",
        {"version": "before", "path": "safe.py", "start_line": 1, "end_line": 1},
    )

    assert result == {
        "ok": False,
        "tool": "read_source",
        "error": "response would exceed cumulative retrieved-source limit; 3 bytes remain",
    }
    assert repository.retrieved_bytes == 0


def test_same_file_references_are_separate_from_definitions(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    source = "TOKEN = 'value'\n\ndef one():\n    return TOKEN\n"
    before.joinpath("sample.py").write_text(source)
    after.joinpath("sample.py").write_text(source)

    result = _repository(before, after).find_references("before", "TOKEN")

    assert result["definition_resolution"] == "resolved"
    assert [(item["path"], item["line"]) for item in result["definitions"]] == [("sample.py", 1)]
    assert [(item["path"], item["line"]) for item in result["references"]] == [("sample.py", 4)]
    assert result["references"][0]["source"] == "def one():\n    return TOKEN\n"


def test_cross_file_references_use_stable_path_line_order(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    for root in (before, after):
        root.joinpath("z.py").write_text("from a import TOKEN\nvalue = TOKEN\n")
        root.joinpath("a.py").write_text("TOKEN = 1\n")
        root.joinpath("m.py").write_text("from a import TOKEN\nvalue = TOKEN\n")

    first = _repository(before, after).find_references("before", "TOKEN")
    second = _repository(before, after).find_references("before", "TOKEN")

    assert first == second
    selected = first["definitions"] + first["references"]
    locations = [(item["path"], item["line"], item["column"]) for item in selected]
    assert first["total_occurrences"] == 5
    assert set(path for path, _, _ in locations) == {"a.py", "m.py", "z.py"}


def test_before_after_isolation_and_path_restriction(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("one.py").write_text("KEY = 1\nprint(KEY)\n")
    before.joinpath("two.py").write_text("print(KEY)\n")
    after.joinpath("one.py").write_text("KEY = 1\n")
    after.joinpath("two.py").write_text("OTHER = 2\n")
    repository = _repository(before, after)

    before_result = repository.find_references("before", "KEY", "two.py")
    after_result = repository.find_references("after", "KEY")

    assert before_result["path"] == "two.py"
    assert before_result["total_references"] == 1
    assert before_result["references"][0]["version"] == "before"
    assert after_result["total_references"] == 0
    assert after_result["total_definitions"] == 1


def test_reference_ambiguity_and_no_match_are_explicit(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    for root in (before, after):
        root.joinpath("one.py").write_text("TOKEN = 1\nprint(TOKEN)\n")
        root.joinpath("two.py").write_text("TOKEN = 2\nprint(TOKEN)\n")
    repository = _repository(before, after)

    ambiguous = repository.find_references("before", "TOKEN")
    missing = repository.find_references("before", "ABSENT")

    assert ambiguous["ambiguous"] is True
    assert ambiguous["definition_resolution"] == "ambiguous"
    assert "not automatically semantically related" in ambiguous["error"]
    assert missing["ok"] is False
    assert missing["definition_resolution"] == "not_found"
    assert missing["error"] == "identifier not found in supported Python source"


def test_reference_count_and_line_limits_are_explicit(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    source = "\n".join(["TOKEN = 1", *("print(TOKEN)" for _ in range(12))]) + "\n"
    before.joinpath("many.py").write_text(source)
    after.joinpath("many.py").write_text(source)

    result = _repository(before, after, matches=3, lines=6).find_references("before", "TOKEN")

    assert result["total_occurrences"] == 13
    assert result["results_limited"] is True
    assert len(result["definitions"]) + len(result["references"]) <= 3
    assert result["returned_source_lines"] <= 6


def test_unsupported_and_binary_reference_lookup_is_explicit(tmp_path: Path) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("sample.js").write_text("const TOKEN = 1;\n")
    after.joinpath("sample.js").write_text("const TOKEN = 1;\n")
    before.joinpath("binary.bin").write_bytes(b"\x00TOKEN\xff")
    after.joinpath("binary.bin").write_bytes(b"\x00TOKEN\xff")
    repository = _repository(before, after)

    for result in (
        repository.find_references("before", "TOKEN", "sample.js"),
        repository.find_references("before", "TOKEN", "binary.bin"),
    ):
        assert result["ok"] is False
        assert result["analysis"] == "unsupported"
        assert "supports Python source only" in result["error"]


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("read_source", [], "tool input must be an object"),
        ("missing_tool", {}, "unknown tool"),
        ("read_source", {"version": "before", "path": "safe.py", "start_line": 1}, "missing"),
        (
            "read_source",
            {"version": "before", "path": "safe.py", "start_line": 0, "end_line": 1},
            "positive integer",
        ),
        ("search_source", {"version": "before", "query": ""}, "non-empty literal"),
        (
            "find_definition",
            {"version": "before", "identifier": "not-valid"},
            "valid identifier",
        ),
        ("find_references", {"version": "before"}, "missing required"),
        (
            "find_references",
            {"version": "before", "identifier": "TOKEN", "extra": True},
            "unexpected",
        ),
    ],
)
def test_malformed_arguments_are_rejected_locally(
    tmp_path: Path, name: str, arguments: Any, error: str
) -> None:
    before, after = _roots(tmp_path)
    before.joinpath("safe.py").write_text("TOKEN = 1\n")
    after.joinpath("safe.py").write_text("TOKEN = 2\n")

    result = _repository(before, after).execute(name, arguments)

    assert result["ok"] is False
    assert error in result["error"]


def test_tool_schema_uses_supported_bedrock_contract() -> None:
    validate_bedrock_tool_config(TOOL_CONFIG)
    assert [tool["toolSpec"]["name"] for tool in TOOL_CONFIG["tools"]] == [
        "read_source",
        "search_source",
        "find_definition",
        "find_references",
    ]


def test_contract_rejects_unverified_schema_keywords() -> None:
    malformed: dict[str, Any] = {
        **TOOL_CONFIG,
        "tools": [*TOOL_CONFIG["tools"]],
    }
    malformed["tools"] = [
        {
            "toolSpec": {
                **TOOL_CONFIG["tools"][0]["toolSpec"],
                "inputSchema": {
                    "json": {
                        **TOOL_CONFIG["tools"][0]["toolSpec"]["inputSchema"]["json"],
                        "minimum": 1,
                    }
                },
            }
        },
        *TOOL_CONFIG["tools"][1:],
    ]

    with pytest.raises(ValueError, match="unsupported schema keys"):
        validate_bedrock_tool_config(malformed)
