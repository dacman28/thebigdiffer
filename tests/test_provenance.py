from __future__ import annotations

from thebigdiffer.provenance import (
    EvidenceProvenance,
    InventoryProducer,
    SourceSpan,
    make_content_id,
)


def test_neutral_provenance_types_are_canonically_owned() -> None:
    assert EvidenceProvenance.__module__ == "thebigdiffer.provenance.model"
    assert SourceSpan.__module__ == "thebigdiffer.provenance.model"


def test_neutral_content_identity_is_stable() -> None:
    material = {"path": "pkg/module.py", "version": "before", "sha256": "abc"}
    producer = InventoryProducer.TREE_INVENTORY

    assert make_content_id("file", producer.value, material) == (
        "file-c7087e32bebcf5ed320e"
    )
