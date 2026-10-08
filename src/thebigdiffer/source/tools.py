"""Validated Bedrock schemas for raw source inspection tools."""

from __future__ import annotations

import copy
from typing import Any

MAX_TOOL_PATH_CHARS = 4096
MAX_SEARCH_QUERY_CHARS = 500
MAX_DEFINITION_IDENTIFIER_CHARS = 256

TOOL_ARGUMENTS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "read_source": (frozenset({"version", "path", "start_line", "end_line"}), frozenset()),
    "search_source": (frozenset({"version", "query"}), frozenset({"path"})),
    "find_definition": (frozenset({"version", "identifier"}), frozenset({"path"})),
}

BASE_TOOL_CONFIG: dict[str, Any] = {
    "tools": [
        {
            "toolSpec": {
                "name": "read_source",
                "description": (
                    "Read an exact inclusive line range from one hash-verified BEFORE or AFTER "
                    "source file. Paths are normalized repository-relative paths."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "version": {"type": "string", "enum": ["before", "after"]},
                            "path": {"type": "string"},
                            "start_line": {"type": "integer"},
                            "end_line": {"type": "integer"},
                        },
                        "required": ["version", "path", "start_line", "end_line"],
                        "additionalProperties": False,
                    }
                },
                "strict": True,
            }
        },
        {
            "toolSpec": {
                "name": "search_source",
                "description": (
                    "Literal (not regex) search across hash-verified BEFORE or AFTER source. "
                    "Optionally restrict to one normalized repository-relative path. Returns "
                    "bounded exact surrounding source and provenance."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "version": {"type": "string", "enum": ["before", "after"]},
                            "query": {"type": "string"},
                            "path": {"type": "string"},
                        },
                        "required": ["version", "query"],
                        "additionalProperties": False,
                    }
                },
                "strict": True,
            }
        },
        {
            "toolSpec": {
                "name": "find_definition",
                "description": (
                    "Find exact Python module-level assignments, functions, or classes for one "
                    "identifier in hash-verified source. Optionally restrict to one path. Reports "
                    "unsupported, missing, oversized, and ambiguous resolution explicitly; use "
                    "literal search_source as fallback."
                ),
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "version": {"type": "string", "enum": ["before", "after"]},
                            "identifier": {"type": "string"},
                            "path": {"type": "string"},
                        },
                        "required": ["version", "identifier"],
                        "additionalProperties": False,
                    }
                },
                "strict": True,
            }
        },
    ],
    "toolChoice": {"auto": {}},
}

FIND_REFERENCES_TOOL: dict[str, Any] = {
    "toolSpec": {
        "name": "find_references",
        "description": (
            "Find source locations that reference an identifier in the hash-verified BEFORE or "
            "AFTER repository snapshot. Returns exact source and provenance. References may be "
            "syntactic or lexical matches and are not automatically semantically related."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "version": {"type": "string", "enum": ["before", "after"]},
                    "identifier": {"type": "string"},
                    "path": {"type": "string"},
                },
                "required": ["version", "identifier"],
                "additionalProperties": False,
            }
        },
        "strict": True,
    }
}

TOOL_CONFIG: dict[str, Any] = copy.deepcopy(BASE_TOOL_CONFIG)
TOOL_CONFIG["tools"].append(FIND_REFERENCES_TOOL)
