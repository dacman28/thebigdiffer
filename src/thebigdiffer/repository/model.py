"""Source-preparation values shared by directory and Git input modes."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

PreparationMode = Literal["directory", "git"]


def _manifest_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class GitPreparationLimits:
    """Local disk and object-count safeguards for snapshot preparation."""

    max_entries: int = 100_000
    max_blob_bytes: int = 2 * 1024 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024 * 1024
    max_symlink_target_bytes: int = 16 * 1024

    def __post_init__(self) -> None:
        if min(
            self.max_entries,
            self.max_blob_bytes,
            self.max_total_bytes,
            self.max_symlink_target_bytes,
        ) <= 0:
            raise ValueError("Git preparation limits must be greater than zero")


@dataclass(frozen=True)
class SourcePreparation:
    """Deterministic upstream provenance for source directories."""

    mode: PreparationMode
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def directory(cls) -> SourcePreparation:
        return cls(mode="directory")

    @classmethod
    def git(cls, metadata: dict[str, Any]) -> SourcePreparation:
        return cls(mode="git", metadata=copy.deepcopy(metadata))

    def serializable(self) -> dict[str, Any]:
        base = {
            "schema_version": 1,
            "mode": self.mode,
            **copy.deepcopy(self.metadata),
        }
        return {**base, "manifest_sha256": _manifest_sha256(base)}


@dataclass
class PreparedGitRepository:
    """Materialized Git snapshots and the cleanup responsibility for their workspace."""

    snapshot_root: Path
    before_directory: Path
    after_directory: Path
    preparation: SourcePreparation
    _closed: bool = field(default=False, init=False, repr=False)

    def cleanup(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.snapshot_root)
        self._closed = True

    def __enter__(self) -> PreparedGitRepository:
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        del exc_type, exc_value, traceback
        self.cleanup()
