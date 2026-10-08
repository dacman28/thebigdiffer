"""Patch-presentation value types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PatchPresentation:
    """Exact model-visible patch and its deterministic provenance."""

    text: str
    sha256: str
    changed_paths: tuple[str, ...]
    patch_records: tuple[dict[str, Any], ...]
    omitted_records: tuple[dict[str, Any], ...]
