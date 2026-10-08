from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from thebigdiffer.ingest import inventory_tree
from thebigdiffer.repository import (
    GitPreparationError,
    GitPreparationLimits,
    GitRepositoryPreparer,
)
from thebigdiffer.repository.git import _parse_ls_tree, _validate_entry_paths


def _git(
    repository: Path,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        input=input_bytes,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _git_text(repository: Path, *arguments: str) -> str:
    return _git(repository, *arguments).decode("utf-8").strip()


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir(parents=True)
    _git(repository, "init")
    _git(repository, "config", "user.name", "TheBigDiffer Tests")
    _git(repository, "config", "user.email", "tests@example.invalid")
    return repository


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", message)
    return _git_text(repository, "rev-parse", "HEAD")


def _two_commits(tmp_path: Path) -> tuple[Path, str, str]:
    repository = _repository(tmp_path)
    repository.joinpath("app.py").write_bytes(b"value = 'before'\n")
    before = _commit(repository, "before")
    repository.joinpath("app.py").write_bytes(b"value = 'after'\n")
    repository.joinpath("data.bin").write_bytes(b"\x00\xff\x10binary\n")
    after = _commit(repository, "after")
    return repository, before, after


def test_resolves_branches_tags_commit_ids_and_relative_refs(tmp_path: Path) -> None:
    repository, before, after = _two_commits(tmp_path)
    branch = _git_text(repository, "branch", "--show-current")
    _git(repository, "tag", "-a", "release-before", before, "-m", "release")

    cases = [
        ("HEAD^", before),
        ("release-before", before),
        (before, before),
        (branch, after),
    ]
    for supplied, expected in cases:
        with GitRepositoryPreparer(repository, supplied, "HEAD").prepare() as prepared:
            record = prepared.preparation.serializable()
            assert record["before"]["supplied_ref"] == supplied
            assert record["before"]["resolved_commit_sha"] == expected
            assert record["after"]["resolved_commit_sha"] == after
            assert len(record["before"]["tree_sha"]) == 40
            assert record["repository"]["git_version"].startswith("git version ")


def test_invalid_repository_ref_and_noncommit_ref_are_explicit(tmp_path: Path) -> None:
    not_repository = tmp_path / "not-repository"
    not_repository.mkdir()
    with pytest.raises(GitPreparationError, match="not a usable local Git repository"):
        GitRepositoryPreparer(not_repository, "HEAD", "HEAD").prepare()

    repository, before, _ = _two_commits(tmp_path / "valid")
    with pytest.raises(GitPreparationError, match="does not resolve to a commit"):
        GitRepositoryPreparer(repository, "missing-ref", "HEAD").prepare()

    blob = _git_text(repository, "rev-parse", f"{before}:app.py")
    _git(repository, "update-ref", "refs/tags/blob-object", blob)
    with pytest.raises(GitPreparationError, match="does not resolve to a commit"):
        GitRepositoryPreparer(repository, "refs/tags/blob-object", "HEAD").prepare()


def test_committed_blobs_ignore_dirty_and_untracked_working_tree(tmp_path: Path) -> None:
    repository, before, after = _two_commits(tmp_path)
    repository.joinpath("app.py").write_bytes(b"value = 'malicious-uncommitted'\n")
    repository.joinpath("untracked.py").write_bytes(b"should_not_exist = True\n")

    with GitRepositoryPreparer(repository, before, after).prepare() as prepared:
        assert prepared.before_directory.joinpath("app.py").read_bytes() == b"value = 'before'\n"
        assert prepared.after_directory.joinpath("app.py").read_bytes() == b"value = 'after'\n"
        assert prepared.after_directory.joinpath("data.bin").read_bytes() == b"\x00\xff\x10binary\n"
        assert not prepared.before_directory.joinpath("untracked.py").exists()
        assert not prepared.after_directory.joinpath("untracked.py").exists()


def test_regular_files_equal_raw_cat_file_blobs_and_preserve_executable_mode(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    script = repository / "script.sh"
    script.write_bytes(b"#!/bin/sh\nprintf 'exact\\n'\n")
    script.chmod(0o755)
    binary = repository / "payload.bin"
    binary.write_bytes(bytes(range(256)))
    commit = _commit(repository, "exact blobs")

    with GitRepositoryPreparer(repository, commit, commit).prepare() as prepared:
        for path in ("script.sh", "payload.bin"):
            blob = _git_text(repository, "rev-parse", f"{commit}:{path}")
            expected = _git(repository, "cat-file", "blob", blob)
            assert prepared.before_directory.joinpath(path).read_bytes() == expected
        assert stat.S_IMODE(prepared.before_directory.joinpath("script.sh").stat().st_mode) == 0o755


def test_archive_and_attribute_transformations_are_not_applied(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.joinpath(".gitattributes").write_text(
        "ignored.txt export-ignore\nident.txt export-subst\n",
        encoding="utf-8",
    )
    repository.joinpath("ignored.txt").write_bytes(b"must remain in raw tree\n")
    repository.joinpath("ident.txt").write_bytes(b"$Format:%H$\n")
    commit = _commit(repository, "attributes")

    with GitRepositoryPreparer(repository, commit, commit).prepare() as prepared:
        assert prepared.before_directory.joinpath("ignored.txt").read_bytes() == (
            b"must remain in raw tree\n"
        )
        assert prepared.before_directory.joinpath("ident.txt").read_bytes() == b"$Format:%H$\n"
        semantics = prepared.preparation.serializable()["object_semantics"]
        assert semantics == {
            "working_tree_used": False,
            "checkout_filters_applied": False,
            "archive_attributes_applied": False,
            "submodules_initialized": False,
            "git_lfs_downloaded": False,
            "network_allowed": False,
        }


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_symlinks_are_materialized_but_never_followed(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    outside = tmp_path / "outside-secret"
    outside.write_text("outside\n", encoding="utf-8")
    repository.joinpath("safe.txt").write_text("safe\n", encoding="utf-8")
    os.symlink("safe.txt", repository / "ordinary-link")
    os.symlink("../../outside-secret", repository / "traversal-link")
    os.symlink("/etc/passwd", repository / "absolute-link")
    repository.joinpath("dir").mkdir()
    os.symlink("../../../other", repository / "dir/nested-link")
    commit = _commit(repository, "symlinks")

    with GitRepositoryPreparer(repository, commit, commit).prepare() as prepared:
        root = prepared.before_directory
        assert root.joinpath("ordinary-link").is_symlink()
        assert os.readlink(root / "ordinary-link") == "safe.txt"
        assert os.readlink(root / "traversal-link") == "../../outside-secret"
        assert os.readlink(root / "absolute-link") == "/etc/passwd"
        assert outside.read_text(encoding="utf-8") == "outside\n"
        record = prepared.preparation.serializable()["before"]
        assert os.readlink(root / "dir/nested-link") == "../../../other"
        assert record["counts"]["symlink_count"] == 4
        assert all(
            entry["followed"] is False
            for entry in record["entries"]
            if entry["kind"] == "symlink"
        )
        inventory = inventory_tree(root, "before")
        symlinks = [item for item in inventory.files if item.file_kind == "symlink"]
        assert len(symlinks) == 4
        assert all(item.ingest_status == "skipped" for item in symlinks)


def test_gitlinks_are_recorded_and_not_materialized(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.joinpath("base.txt").write_text("base\n", encoding="utf-8")
    target = _commit(repository, "base")
    _git(
        repository,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{target},vendor/dependency",
    )
    _git(repository, "commit", "-m", "gitlink")
    commit = _git_text(repository, "rev-parse", "HEAD")

    with GitRepositoryPreparer(repository, target, commit).prepare() as prepared:
        assert not prepared.after_directory.joinpath("vendor/dependency").exists()
        after = prepared.preparation.serializable()["after"]
        assert after["counts"]["gitlink_count"] == 1
        gitlink = next(item for item in after["entries"] if item["kind"] == "gitlink")
        assert gitlink["status"] == "skipped"
        assert "not initialized or traversed" in gitlink["reason"]


def test_manifest_is_deterministic_and_workspace_is_cleaned(tmp_path: Path) -> None:
    repository, before, after = _two_commits(tmp_path)
    first = GitRepositoryPreparer(repository, before, after).prepare()
    first_root = first.snapshot_root
    first_record = first.preparation.serializable()
    first.cleanup()
    assert not first_root.exists()

    with GitRepositoryPreparer(repository, before, after).prepare() as second:
        assert second.preparation.serializable() == first_record
        assert second.preparation.serializable()["materialization_status"] == "complete"
        assert len(second.preparation.serializable()["manifest_sha256"]) == 64


def test_preparation_limits_fail_before_unbounded_materialization(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.joinpath("large.bin").write_bytes(b"x" * 32)
    commit = _commit(repository, "large")
    limits = GitPreparationLimits(max_blob_bytes=16)
    with pytest.raises(GitPreparationError, match="max_blob_bytes=16"):
        GitRepositoryPreparer(repository, commit, commit, limits=limits).prepare()


def test_path_validation_rejects_traversal_ambiguity_and_collisions() -> None:
    object_id = "a" * 40
    with pytest.raises(GitPreparationError, match="unsafe Git tree path"):
        _validate_entry_paths(
            [{"mode": "100644", "object_type": "blob", "object_id": object_id, "path": "../x"}]
        )
    with pytest.raises(GitPreparationError, match="unsafe Git tree path"):
        _validate_entry_paths(
            [{"mode": "100644", "object_type": "blob", "object_id": object_id, "path": "a\\b"}]
        )
    with pytest.raises(GitPreparationError, match="collision"):
        _validate_entry_paths(
            [
                {"mode": "100644", "object_type": "blob", "object_id": object_id, "path": "A"},
                {"mode": "100644", "object_type": "blob", "object_id": object_id, "path": "a"},
            ]
        )
    with pytest.raises(GitPreparationError, match="non-directory parent"):
        _validate_entry_paths(
            [
                {"mode": "120000", "object_type": "blob", "object_id": object_id, "path": "dir"},
                {
                    "mode": "100644",
                    "object_type": "blob",
                    "object_id": object_id,
                    "path": "dir/file",
                },
            ]
        )


def test_committed_case_collision_is_rejected_portably(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    blob = _git(repository, "hash-object", "-w", "--stdin", input_bytes=b"content\n").decode(
        "ascii"
    ).strip()
    tree = _git(
        repository,
        "mktree",
        "-z",
        input_bytes=(
            f"100644 blob {blob}\tCase.txt\0"
            f"100644 blob {blob}\tcase.txt\0"
        ).encode(),
    ).decode("ascii").strip()
    commit = _git_text(repository, "commit-tree", tree, "-m", "case collision")

    with pytest.raises(GitPreparationError, match="case or Unicode-normalization path collision"):
        GitRepositoryPreparer(repository, commit, commit).prepare()


def test_malformed_tree_output_is_rejected() -> None:
    with pytest.raises(GitPreparationError, match="not NUL terminated"):
        _parse_ls_tree(b"100644 blob " + b"a" * 40 + b"\tfile")
    with pytest.raises(GitPreparationError, match="malformed or non-UTF-8"):
        _parse_ls_tree(b"bad\0")
    with pytest.raises(GitPreparationError, match="unsupported Git object type"):
        _parse_ls_tree(b"100644 tree " + b"a" * 40 + b"\tfile\0")


def test_git_unavailable_and_object_read_failure_are_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(GitPreparationError, match="Git executable is unavailable"):
        GitRepositoryPreparer(tmp_path, "HEAD", "HEAD")

    monkeypatch.undo()
    repository, before, _ = _two_commits(tmp_path / "objects")
    preparer = GitRepositoryPreparer(repository, before, before)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    with pytest.raises(GitPreparationError, match="Git command 'cat-file' failed"):
        preparer._materialize_entries(
            [
                {
                    "mode": "100644",
                    "object_type": "blob",
                    "object_id": "0" * 40,
                    "path": "missing.txt",
                }
            ],
            snapshot,
        )


def test_git_executable_disappearing_during_blob_read_is_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository, before, _ = _two_commits(tmp_path)
    preparer = GitRepositoryPreparer(repository, before, before)
    object_id = _git_text(repository, "rev-parse", f"{before}:app.py")
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()

    def fail_to_start(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        del args, kwargs
        raise OSError("executable disappeared")

    monkeypatch.setattr(subprocess, "Popen", fail_to_start)
    root_fd = os.open(snapshot, os.O_RDONLY)
    try:
        with pytest.raises(GitPreparationError, match="cannot execute Git object read"):
            preparer._materialize_regular(
                root_fd,
                "app.py",
                object_id,
                executable=False,
                expected_size=len(b"value = 'before'\n"),
            )
    finally:
        os.close(root_fd)


def test_snapshot_root_collision_fails_closed(tmp_path: Path) -> None:
    repository, before, _ = _two_commits(tmp_path / "repository-case")
    preparer = GitRepositoryPreparer(repository, before, before)
    snapshot = tmp_path / "occupied"
    snapshot.mkdir()
    snapshot.joinpath("existing").write_text("occupied", encoding="utf-8")
    with pytest.raises(GitPreparationError, match="snapshot root collision"):
        preparer._materialize_entries([], snapshot)


def test_manifest_serializes_as_stable_json(tmp_path: Path) -> None:
    repository, before, after = _two_commits(tmp_path)
    with GitRepositoryPreparer(repository, before, after).prepare() as prepared:
        first = json.dumps(prepared.preparation.serializable(), sort_keys=True)
        second = json.dumps(prepared.preparation.serializable(), sort_keys=True)
        assert first == second
