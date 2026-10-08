"""Architecture-neutral deterministic identity and provenance values."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, TypeAlias

ContentIdentityKind: TypeAlias = Literal["file", "change", "fact", "context"]


class InventoryProducer(StrEnum):
    """Deterministic producer identities used by safe source inventory."""

    TREE_INVENTORY = "thebigdiffer.ingest.tree.v1"
    TREE_DIAGNOSTIC = "thebigdiffer.ingest.diagnostic.v1"


@dataclass(frozen=True)
class SourceSpan:
    """Exact inventoried source supporting a deterministic fact."""

    version: Literal["before", "after"]
    path: str
    file_evidence_id: str
    start_line: int
    end_line: int
    source: str


@dataclass(frozen=True)
class EvidenceProvenance:
    """Producer and exact upstream identities for deterministic material."""

    producer: str
    input_evidence_ids: tuple[str, ...] = ()
    source_spans: tuple[SourceSpan, ...] = ()


def make_content_id(
    kind: ContentIdentityKind,
    producer: str,
    material: object,
) -> str:
    """Return the existing stable content-derived identity encoding."""
    if kind not in {"file", "change", "fact", "context"}:
        raise ValueError(f"unsupported evidence kind: {kind!r}")
    encoded = json.dumps(
        {"producer": producer, "material": material},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{kind}-{hashlib.sha256(encoded).hexdigest()[:20]}"
