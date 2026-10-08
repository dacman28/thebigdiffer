from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path

import pytest

import thebigdiffer.ingest.tree as ingest_tree
from thebigdiffer.ingest import (
    IngestionError,
    IngestionLimits,
    inventory_tree,
    normalize_relative_path,
)


def test_inventory_hashing_language_and_normalized_paths(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    nested = root / "pkg"
    nested.mkdir(parents=True)
    content = b"def answer():\n    return 42\n"
    (nested / "module.py").write_bytes(content)

    inventory = inventory_tree(root, "before")

    assert inventory.file_count == 1
    record = inventory.files[0]
    assert record.path == "pkg/module.py"
    assert record.file_kind == "source"
    assert record.language == "Python"
    assert record.sha256 == hashlib.sha256(content).hexdigest()
    assert record.size == len(content)
    assert record.evidence_id.startswith("file-")


def test_normalize_relative_path_handles_separators_and_rejects_escape() -> None:
    assert normalize_relative_path("pkg\\module.py") == "pkg/module.py"
    assert normalize_relative_path("pkg/module.py") == "pkg/module.py"
    for unsafe in ("../escape.py", "pkg/../escape.py", "/absolute.py", "C:\\escape.py", ""):
        with pytest.raises(ValueError):
            normalize_relative_path(unsafe)


def test_binary_file_is_not_classified_as_source_from_suffix(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    payload = b"print('text prefix')\n" + b"\x00\xff" + b"tail"
    (root / "misleading.py").write_bytes(payload)

    record = inventory_tree(root, "before").files[0]

    assert record.file_kind == "binary"
    assert record.language is None
    assert record.sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_symlinks_are_recorded_but_never_followed_outside_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("outside-content", encoding="utf-8")
    root = tmp_path / "tree"
    root.mkdir()
    (root / "file-link").symlink_to(secret)
    (root / "dir-link").symlink_to(outside, target_is_directory=True)

    inventory = inventory_tree(root, "before")

    assert [item.path for item in inventory.files] == ["dir-link", "file-link"]
    assert all(item.file_kind == "symlink" for item in inventory.files)
    assert all(item.ingest_status == "skipped" for item in inventory.files)
    assert not any(item.path.endswith("secret.txt") for item in inventory.files)
    assert hashlib.sha256(b"outside-content").hexdigest() not in {
        item.sha256 for item in inventory.files
    }


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks are unavailable")
def test_symlink_root_is_rejected(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(IngestionError, match="must not be a symlink"):
        inventory_tree(linked, "before")


def test_non_directory_root_is_rejected(tmp_path: Path) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_text("pass\n", encoding="utf-8")

    with pytest.raises(IngestionError, match="must be a directory"):
        inventory_tree(source_file, "before")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_fifo_is_explicitly_skipped_without_being_read(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    os.mkfifo(root / "events.py")

    record = inventory_tree(root, "before").files[0]

    assert record.file_kind == "unsupported"
    assert record.ingest_status == "skipped"
    assert record.sha256 is None
    assert record.issue == "unsupported filesystem object: fifo"


def test_unreadable_file_is_a_recoverable_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "blocked.txt").write_text("content", encoding="utf-8")
    real_open = os.open

    def deny_file_open(
        path: str | os.PathLike[str], flags: int, *, dir_fd: int | None = None
    ) -> int:
        if path == "blocked.txt":
            raise PermissionError(errno.EACCES, "permission denied")
        return real_open(path, flags, dir_fd=dir_fd)

    monkeypatch.setattr(ingest_tree, "_secure_traversal_supported", lambda: True)
    monkeypatch.setattr(os, "open", deny_file_open)

    record = inventory_tree(root, "before").files[0]

    assert record.file_kind == "unreadable"
    assert record.ingest_status == "error"
    assert record.sha256 is None
    assert record.issue and "OS error" in record.issue


def test_oversized_file_is_explicitly_skipped(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "large.txt").write_text("12345", encoding="utf-8")

    inventory = inventory_tree(
        root,
        "before",
        IngestionLimits(max_entries=10, max_file_bytes=4, max_total_bytes=10),
    )

    record = inventory.files[0]
    assert record.ingest_status == "skipped"
    assert record.sha256 is None
    assert record.issue == "file exceeds max_file_bytes"


def test_total_byte_and_entry_limits_are_explicit(tmp_path: Path) -> None:
    byte_root = tmp_path / "byte-tree"
    byte_root.mkdir()
    (byte_root / "a.txt").write_text("1234", encoding="utf-8")
    (byte_root / "b.txt").write_text("5678", encoding="utf-8")

    byte_inventory = inventory_tree(
        byte_root,
        "before",
        IngestionLimits(max_entries=10, max_file_bytes=10, max_total_bytes=6),
    )

    assert byte_inventory.files[0].ingest_status == "inventoried"
    assert byte_inventory.files[1].ingest_status == "skipped"
    assert byte_inventory.files[1].issue == "tree exceeds max_total_bytes"

    entry_root = tmp_path / "entry-tree"
    entry_root.mkdir()
    (entry_root / "a.txt").write_text("a", encoding="utf-8")
    (entry_root / "b.txt").write_text("b", encoding="utf-8")

    entry_inventory = inventory_tree(
        entry_root,
        "before",
        IngestionLimits(max_entries=1, max_file_bytes=10, max_total_bytes=10),
    )

    assert entry_inventory.files == ()
    assert len(entry_inventory.ingest_diagnostics) == 1
    assert "max_entries=1" in entry_inventory.ingest_diagnostics[0].reason


def test_utf8_character_split_across_hash_chunks_is_text(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    payload = b"a" * (1024 * 1024 - 1) + "€".encode()
    (root / "boundary.txt").write_bytes(payload)

    record = inventory_tree(root, "before").files[0]

    assert record.file_kind == "text"
    assert record.sha256 == hashlib.sha256(payload).hexdigest()


def test_root_hash_ignores_mtime_and_package_role(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    (before / "same.txt").write_text("same", encoding="utf-8")
    (after / "same.txt").write_text("same", encoding="utf-8")
    os.utime(before / "same.txt", (1, 1))
    os.utime(after / "same.txt", (2, 2))

    old = inventory_tree(before, "before")
    new = inventory_tree(after, "after")

    assert old.root_hash == new.root_hash
    assert old.files[0].evidence_id != new.files[0].evidence_id
