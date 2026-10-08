"""Hash-verified access to immutable BEFORE and AFTER source snapshots."""

from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from thebigdiffer.ingest import (
    FileRecord,
    PackageInventory,
    inventory_tree,
    normalize_relative_path,
    read_inventoried_text,
)
from thebigdiffer.source.model import SourceToolResult, SourceVersion
from thebigdiffer.source.tools import (
    MAX_DEFINITION_IDENTIFIER_CHARS,
    MAX_SEARCH_QUERY_CHARS,
    MAX_TOOL_PATH_CHARS,
    TOOL_ARGUMENTS,
)


class SourceToolError(ValueError):
    """An explicit, model-visible source tool failure."""


@dataclass(frozen=True)
class SourceSnapshot:
    """One inventoried repository version."""

    version: SourceVersion
    root: Path
    inventory: PackageInventory
    files: dict[str, FileRecord]


class SourceRepository:
    """The validated four-tool source repository."""

    def __init__(
        self,
        before_root: Path,
        after_root: Path,
        *,
        max_lines_per_response: int,
        max_retrieved_bytes: int,
        search_max_matches: int,
        search_context_lines: int,
    ) -> None:
        before_inventory = inventory_tree(before_root, "before")
        after_inventory = inventory_tree(after_root, "after")
        self.snapshots: dict[SourceVersion, SourceSnapshot] = {
            "before": SourceSnapshot(
                "before",
                before_root,
                before_inventory,
                {item.path: item for item in before_inventory.files},
            ),
            "after": SourceSnapshot(
                "after",
                after_root,
                after_inventory,
                {item.path: item for item in after_inventory.files},
            ),
        }
        self.max_lines_per_response = max_lines_per_response
        self.max_retrieved_bytes = max_retrieved_bytes
        self.search_max_matches = search_max_matches
        self.search_context_lines = search_context_lines
        self.retrieved_bytes = 0

    def inventory_record(self) -> dict[str, Any]:
        return {
            version: {
                "version": snapshot.inventory.version,
                "root_hash": snapshot.inventory.root_hash,
                "file_count": snapshot.inventory.file_count,
                "total_size": snapshot.inventory.total_size,
                "diagnostics": [
                    {"path": item.path, "status": item.status, "reason": item.reason}
                    for item in snapshot.inventory.ingest_diagnostics
                ],
                "files": [
                    {
                        "path": item.path,
                        "file_kind": item.file_kind,
                        "language": item.language,
                        "size": item.size,
                        "sha256": item.sha256,
                        "ingest_status": item.ingest_status,
                        "issue": item.issue,
                        "link_target": item.link_target,
                    }
                    for item in snapshot.inventory.files
                ],
            }
            for version, snapshot in self.snapshots.items()
        }

    def execute(self, name: str, arguments: object) -> SourceToolResult:
        try:
            if name == "find_references":
                self._validate_reference_arguments(arguments)
                assert isinstance(arguments, dict)
                return self.find_references(**arguments)
            self._validate_arguments(name, arguments)
            assert isinstance(arguments, dict)
            if name == "read_source":
                return self.read_source(**arguments)
            if name == "search_source":
                return self.search_source(**arguments)
            if name == "find_definition":
                return self.find_definition(**arguments)
            return self._error(name, f"unknown tool: {name}")
        except (SourceToolError, TypeError, ValueError) as error:
            return self._error(name, str(error))

    def read_source(
        self, version: object, path: object, start_line: object, end_line: object
    ) -> SourceToolResult:
        self._snapshot(version)
        self._path(path)
        start = self._positive_int(start_line, "start_line")
        end = self._positive_int(end_line, "end_line")
        if end < start:
            raise SourceToolError("end_line must be greater than or equal to start_line")
        if end - start + 1 > self.max_lines_per_response:
            raise SourceToolError(
                f"requested range exceeds {self.max_lines_per_response} source-line limit"
            )
        snapshot, record, text = self._read(version, path)
        lines = text.splitlines(keepends=True)
        if start > len(lines):
            raise SourceToolError(
                f"start_line {start} exceeds file length {len(lines)} for {record.path}"
            )
        actual_end = min(end, len(lines))
        source = "".join(lines[start - 1 : actual_end])
        self._charge(source)
        return {
            "ok": True,
            "tool": "read_source",
            "provenance": {
                "version": snapshot.version,
                "path": record.path,
                "start_line": start,
                "end_line": actual_end,
                "file_sha256": record.sha256,
            },
            "source": source,
            "retrieved_source_bytes": len(source.encode("utf-8")),
            "cumulative_retrieved_source_bytes": self.retrieved_bytes,
        }

    def search_source(
        self, version: object, query: object, path: object | None = None
    ) -> SourceToolResult:
        snapshot = self._snapshot(version)
        if not isinstance(query, str) or not query:
            raise SourceToolError("query must be a non-empty literal string")
        if len(query) > MAX_SEARCH_QUERY_CHARS:
            raise SourceToolError(f"query exceeds {MAX_SEARCH_QUERY_CHARS}-character limit")
        self._optional_path(path)
        records = self._candidate_records(snapshot, path)
        matches: list[dict[str, Any]] = []
        diagnostics: list[dict[str, str]] = []
        total_lines = 0
        total_source = ""
        for record in records:
            try:
                text = self._verified_text(snapshot, record)
            except SourceToolError as error:
                diagnostics.append({"path": record.path, "error": str(error)})
                continue
            lines = text.splitlines(keepends=True)
            for index, line in enumerate(lines):
                if query not in line:
                    continue
                start = max(1, index + 1 - self.search_context_lines)
                end = min(len(lines), index + 1 + self.search_context_lines)
                count = end - start + 1
                if total_lines + count > self.max_lines_per_response:
                    break
                source = "".join(lines[start - 1 : end])
                matches.append(
                    {
                        "version": snapshot.version,
                        "path": record.path,
                        "line": index + 1,
                        "start_line": start,
                        "end_line": end,
                        "file_sha256": record.sha256,
                        "source": source,
                    }
                )
                total_lines += count
                total_source += source
                if len(matches) >= self.search_max_matches:
                    break
            if (
                len(matches) >= self.search_max_matches
                or total_lines >= self.max_lines_per_response
            ):
                break
        self._charge(total_source)
        return {
            "ok": True,
            "tool": "search_source",
            "version": snapshot.version,
            "query": query,
            "path": self._optional_path(path),
            "literal_search": True,
            "matches": matches,
            "match_limit": self.search_max_matches,
            "matches_limited": len(matches) >= self.search_max_matches,
            "diagnostics": diagnostics,
            "retrieved_source_bytes": len(total_source.encode("utf-8")),
            "cumulative_retrieved_source_bytes": self.retrieved_bytes,
        }

    def find_definition(
        self, version: object, identifier: object, path: object | None = None
    ) -> SourceToolResult:
        snapshot = self._snapshot(version)
        if (
            not isinstance(identifier, str)
            or len(identifier) > MAX_DEFINITION_IDENTIFIER_CHARS
            or not identifier.isidentifier()
        ):
            raise SourceToolError("identifier must be one valid identifier token")
        self._optional_path(path)
        records = self._candidate_records(snapshot, path)
        python_records = [item for item in records if item.language == "Python"]
        if path is not None and not python_records:
            normalized = self._optional_path(path)
            return {
                "ok": False,
                "tool": "find_definition",
                "version": snapshot.version,
                "identifier": identifier,
                "path": normalized,
                "resolution": "unsupported",
                "error": "definition lookup supports Python source only; use search_source",
                "definitions": [],
            }
        definitions: list[dict[str, Any]] = []
        diagnostics: list[dict[str, str]] = []
        total_lines = 0
        total_source = ""
        oversized: list[dict[str, Any]] = []
        for record in python_records:
            try:
                text = self._verified_text(snapshot, record)
                tree = ast.parse(text, filename=record.path)
            except (SourceToolError, SyntaxError) as parse_error:
                diagnostics.append({"path": record.path, "error": str(parse_error)})
                continue
            lines = text.splitlines(keepends=True)
            for node, kind in self._python_definitions(tree, identifier):
                start = node.lineno
                end = int(getattr(node, "end_lineno", start) or start)
                count = end - start + 1
                location = {
                    "version": snapshot.version,
                    "path": record.path,
                    "start_line": start,
                    "end_line": end,
                    "file_sha256": record.sha256,
                    "kind": kind,
                }
                if (
                    count > self.max_lines_per_response
                    or total_lines + count > self.max_lines_per_response
                ):
                    oversized.append(location)
                    continue
                source = "".join(lines[start - 1 : end])
                definitions.append({**location, "source": source})
                total_lines += count
                total_source += source
        self._charge(total_source)
        if not definitions and oversized:
            resolution = "oversized"
            resolution_error = (
                "matching definition exceeds the source-line limit; use read_source on the "
                "reported exact range"
            )
        elif not definitions:
            resolution = "not_found"
            resolution_error = "no supported Python definition found; use search_source"
        elif len(definitions) + len(oversized) > 1:
            resolution = "ambiguous"
            resolution_error = "multiple definitions found; inspect the reported provenance"
        else:
            resolution = "resolved"
            resolution_error = None
        return {
            "ok": bool(definitions),
            "tool": "find_definition",
            "version": snapshot.version,
            "identifier": identifier,
            "path": self._optional_path(path),
            "resolution": resolution,
            "error": resolution_error,
            "definitions": definitions,
            "oversized_definitions": oversized,
            "diagnostics": diagnostics,
            "retrieved_source_bytes": len(total_source.encode("utf-8")),
            "cumulative_retrieved_source_bytes": self.retrieved_bytes,
        }

    def find_references(
        self, version: object, identifier: object, path: object | None = None
    ) -> SourceToolResult:
        snapshot = self._snapshot(version)
        name = self._identifier(identifier)
        normalized_path = self._optional_path(path)
        records = self._candidate_records(snapshot, normalized_path)
        python_records = [record for record in records if record.language == "Python"]
        unsupported = [record.path for record in records if record.language != "Python"]
        if normalized_path is not None and not python_records:
            return {
                "ok": False,
                "tool": "find_references",
                "version": snapshot.version,
                "identifier": name,
                "path": normalized_path,
                "analysis": "unsupported",
                "definition_resolution": "unsupported",
                "error": (
                    "reference lookup supports Python source only; use search_source for "
                    "literal fallback"
                ),
                "definitions": [],
                "references": [],
                "total_occurrences": 0,
                "total_definitions": 0,
                "total_references": 0,
                "results_limited": False,
                "unsupported_paths": unsupported,
                "diagnostics": [],
            }

        occurrences: list[dict[str, Any]] = []
        diagnostics: list[dict[str, str]] = []
        for record in python_records:
            try:
                text = self._verified_text(snapshot, record)
                occurrences.extend(self._python_occurrences(snapshot, record, text, name))
            except (SourceToolError, SyntaxError, tokenize.TokenError, ValueError) as error:
                diagnostics.append({"path": record.path, "error": str(error)})

        occurrences.sort(
            key=lambda item: (item["path"], item["line"], item["column"], item["classification"])
        )
        total_definitions = sum(item["classification"] == "definition" for item in occurrences)
        total_references = len(occurrences) - total_definitions
        selected: list[dict[str, Any]] = []
        selected_lines = 0
        selected_source = ""
        for occurrence in occurrences:
            line_count = occurrence["end_line"] - occurrence["start_line"] + 1
            if len(selected) >= self.search_max_matches:
                break
            if selected_lines + line_count > self.max_lines_per_response:
                break
            selected.append(occurrence)
            selected_lines += line_count
            selected_source += occurrence["source"]
        self._charge(selected_source)

        definitions = [item for item in selected if item["classification"] == "definition"]
        references = [item for item in selected if item["classification"] == "reference"]
        if total_definitions == 1:
            definition_resolution = "resolved"
            ambiguity = False
        elif total_definitions > 1:
            definition_resolution = "ambiguous"
            ambiguity = True
        else:
            definition_resolution = "not_found"
            ambiguity = False
        analysis = "partial" if diagnostics else "python_syntax"
        if not occurrences:
            result_error = "identifier not found in supported Python source"
        elif ambiguity:
            result_error = (
                "identifier resolution is ambiguous; candidate occurrences are lexical/syntactic "
                "and are not automatically semantically related"
            )
        else:
            result_error = None
        return {
            "ok": bool(occurrences),
            "tool": "find_references",
            "version": snapshot.version,
            "identifier": name,
            "path": normalized_path,
            "analysis": analysis,
            "language_support": "Python syntax only",
            "definition_resolution": definition_resolution,
            "ambiguous": ambiguity,
            "error": result_error,
            "definitions": definitions,
            "references": references,
            "total_occurrences": len(occurrences),
            "total_definitions": total_definitions,
            "total_references": total_references,
            "result_limit": self.search_max_matches,
            "results_limited": len(selected) < len(occurrences),
            "returned_source_lines": selected_lines,
            "retrieved_source_bytes": len(selected_source.encode("utf-8")),
            "cumulative_retrieved_source_bytes": self.retrieved_bytes,
            "unsupported_path_count": len(unsupported),
            "unsupported_paths": unsupported if normalized_path is not None else [],
            "diagnostics": diagnostics,
        }

    def _snapshot(self, version: object) -> SourceSnapshot:
        if version not in {"before", "after"}:
            raise SourceToolError("version must be exactly 'before' or 'after'")
        return self.snapshots[version]

    def _validate_arguments(self, name: str, arguments: object) -> None:
        contract = TOOL_ARGUMENTS.get(name)
        if contract is None:
            raise SourceToolError(f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            raise SourceToolError("tool input must be an object")
        required, optional = contract
        supplied = set(arguments)
        missing = required - supplied
        if missing:
            raise SourceToolError(f"missing required tool arguments: {sorted(missing)}")
        unexpected = supplied - required - optional
        if unexpected:
            raise SourceToolError(f"unexpected tool arguments: {sorted(unexpected, key=str)}")

        self._snapshot(arguments["version"])
        path = arguments.get("path")
        if path is not None:
            self._path(path)
        if name == "read_source":
            start = self._positive_int(arguments["start_line"], "start_line")
            end = self._positive_int(arguments["end_line"], "end_line")
            if end < start:
                raise SourceToolError("end_line must be greater than or equal to start_line")
            if end - start + 1 > self.max_lines_per_response:
                raise SourceToolError(
                    f"requested range exceeds {self.max_lines_per_response} source-line limit"
                )
        elif name == "search_source":
            query = arguments["query"]
            if not isinstance(query, str) or not query:
                raise SourceToolError("query must be a non-empty literal string")
            if len(query) > MAX_SEARCH_QUERY_CHARS:
                raise SourceToolError(f"query exceeds {MAX_SEARCH_QUERY_CHARS}-character limit")
        else:
            identifier = arguments["identifier"]
            if (
                not isinstance(identifier, str)
                or len(identifier) > MAX_DEFINITION_IDENTIFIER_CHARS
                or not identifier.isidentifier()
            ):
                raise SourceToolError("identifier must be one valid identifier token")

    def _validate_reference_arguments(self, arguments: object) -> None:
        if not isinstance(arguments, dict):
            raise SourceToolError("tool input must be an object")
        required = {"version", "identifier"}
        optional = {"path"}
        missing = required - set(arguments)
        if missing:
            raise SourceToolError(f"missing required tool arguments: {sorted(missing)}")
        unexpected = set(arguments) - required - optional
        if unexpected:
            raise SourceToolError(f"unexpected tool arguments: {sorted(unexpected, key=str)}")
        self._snapshot(arguments["version"])
        self._identifier(arguments["identifier"])
        if arguments.get("path") is not None:
            self._path(arguments["path"])

    def _read(self, version: object, path: object) -> tuple[SourceSnapshot, FileRecord, str]:
        snapshot = self._snapshot(version)
        normalized = self._path(path)
        record = snapshot.files.get(normalized)
        if record is None:
            raise SourceToolError(f"path is not in the {snapshot.version} inventory: {normalized}")
        return snapshot, record, self._verified_text(snapshot, record)

    def _verified_text(self, snapshot: SourceSnapshot, record: FileRecord) -> str:
        if record.ingest_status != "inventoried" or record.file_kind not in {"source", "text"}:
            raise SourceToolError(
                f"path is not inventoried text source: {record.path} ({record.file_kind})"
            )
        if record.size is None:
            raise SourceToolError(f"inventoried size unavailable: {record.path}")
        result = read_inventoried_text(snapshot.root, record, record.size + 1)
        if result.status != "available" or result.text is None:
            raise SourceToolError(
                f"source verification failed for {record.path}: {result.error or result.status}"
            )
        return result.text

    def _candidate_records(self, snapshot: SourceSnapshot, path: object | None) -> list[FileRecord]:
        if path is not None:
            normalized = self._path(path)
            record = snapshot.files.get(normalized)
            if record is None:
                raise SourceToolError(
                    f"path is not in the {snapshot.version} inventory: {normalized}"
                )
            return [record]
        return [
            item
            for item in snapshot.inventory.files
            if item.ingest_status == "inventoried" and item.file_kind in {"source", "text"}
        ]

    def _charge(self, source: str) -> None:
        size = len(source.encode("utf-8"))
        if self.retrieved_bytes + size > self.max_retrieved_bytes:
            remaining = self.max_retrieved_bytes - self.retrieved_bytes
            raise SourceToolError(
                f"response would exceed cumulative retrieved-source limit; {remaining} bytes remain"
            )
        self.retrieved_bytes += size

    @staticmethod
    def _python_definitions(tree: ast.Module, identifier: str) -> list[tuple[ast.stmt, str]]:
        found: list[tuple[ast.stmt, str]] = []
        for node in tree.body:
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == identifier
            ):
                found.append((node, "function"))
            elif isinstance(node, ast.ClassDef) and node.name == identifier:
                found.append((node, "class"))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(
                    isinstance(target, ast.Name) and target.id == identifier for target in targets
                ):
                    found.append((node, "module_assignment"))
        return found

    @staticmethod
    def _positive_int(value: object, label: str) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise SourceToolError(f"{label} must be a positive integer")
        return value

    @staticmethod
    def _path(value: object) -> str:
        if not isinstance(value, str):
            raise SourceToolError("path must be a string")
        if len(value) > MAX_TOOL_PATH_CHARS:
            raise SourceToolError(f"path exceeds {MAX_TOOL_PATH_CHARS}-character limit")
        try:
            return normalize_relative_path(value)
        except ValueError as error:
            raise SourceToolError(str(error)) from error

    @classmethod
    def _optional_path(cls, value: object | None) -> str | None:
        return None if value is None else cls._path(value)

    @staticmethod
    def _identifier(value: object) -> str:
        if (
            not isinstance(value, str)
            or len(value) > MAX_DEFINITION_IDENTIFIER_CHARS
            or not value.isidentifier()
        ):
            raise SourceToolError("identifier must be one valid identifier token")
        return value

    def _python_occurrences(
        self, snapshot: SourceSnapshot, record: FileRecord, text: str, identifier: str
    ) -> list[dict[str, Any]]:
        tree = ast.parse(text, filename=record.path)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        definition_positions = _definition_positions(tree, tokens, identifier)
        lines = text.splitlines(keepends=True)
        found: list[dict[str, Any]] = []
        for token in tokens:
            if token.type != tokenize.NAME or token.string != identifier:
                continue
            line, column = token.start
            end_line, end_column = token.end
            start_context = max(1, line - self.search_context_lines)
            end_context = min(len(lines), line + self.search_context_lines)
            source = "".join(lines[start_context - 1 : end_context])
            classification = "definition" if token.start in definition_positions else "reference"
            found.append(
                {
                    "version": snapshot.version,
                    "path": record.path,
                    "line": line,
                    "column": column,
                    "match_end_line": end_line,
                    "match_end_column": end_column,
                    "start_line": start_context,
                    "end_line": end_context,
                    "file_sha256": record.sha256,
                    "identifier": identifier,
                    "classification": classification,
                    "classification_basis": (
                        "python_ast_binding"
                        if classification == "definition"
                        else "python_identifier_token"
                    ),
                    "source": source,
                }
            )
        return found

    @staticmethod
    def _error(tool: str, message: str) -> SourceToolResult:
        return {"ok": False, "tool": tool, "error": message}


def _definition_positions(
    tree: ast.AST, tokens: list[tokenize.TokenInfo], identifier: str
) -> set[tuple[int, int]]:
    positions: set[tuple[int, int]] = set()
    definition_lines: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Name)
            and node.id == identifier
            and isinstance(node.ctx, (ast.Store, ast.Param))
        ):
            positions.add((node.lineno, node.col_offset))
        elif isinstance(node, ast.arg) and node.arg == identifier:
            positions.add((node.lineno, node.col_offset))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == identifier:
                definition_lines.append((node.lineno, node.col_offset))
        elif isinstance(node, ast.alias):
            bound_name = node.asname or node.name.split(".")[0]
            if bound_name == identifier:
                definition_lines.append((node.lineno, node.col_offset))
    for line, minimum_column in definition_lines:
        candidates = [
            token.start
            for token in tokens
            if token.type == tokenize.NAME
            and token.string == identifier
            and token.start[0] == line
            and token.start[1] >= minimum_column
        ]
        if candidates:
            positions.add(min(candidates))
    return positions
