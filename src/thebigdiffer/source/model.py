"""Source-repository public types."""

from __future__ import annotations

from typing import Any, Literal, TypeAlias

SourceVersion: TypeAlias = Literal["before", "after"]
SourceToolResult: TypeAlias = dict[str, Any]
