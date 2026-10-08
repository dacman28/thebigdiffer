from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from thebigdiffer.ingest import inventory_tree
from thebigdiffer.repository import GitPreparationError, GitRepositoryPreparer


def _git(repository: Path, *arguments: str, data: bytes | None = None) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_AUTHOR_NAME="Prefix identity tests",
        GIT_AUTHOR_EMAIL="tests@example.invalid",
        GIT_COMMITTER_NAME="Prefix identity tests",
        GIT_COMMITTER_EMAIL="tests@example.invalid",
    )
    return (
        subprocess.run(
            [
                "git",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "commit.gpgsign=false",
                "-C",
                str(repository),
                *arguments,
            ],
            input=data,
            capture_output=True,
            check=True,
            env=environment,
        )
        .stdout.decode("utf-8")
        .strip()
    )


def _tree(repository: Path, files: dict[str, bytes]) -> str:
    """Create raw Git paths without asking the host filesystem to represent them."""
    entries: list[str] = []
    directories: dict[str, dict[str, bytes]] = {}
    for path, payload in files.items():
        first, separator, rest = path.partition("/")
        if separator:
            directories.setdefault(first, {})[rest] = payload
        else:
            blob = _git(repository, "hash-object", "-w", "--stdin", data=payload)
            entries.append(f"100644 blob {blob}\t{first}\0")
    for directory, children in directories.items():
        tree = _tree(repository, children)
        entries.append(f"040000 tree {tree}\t{directory}\0")
    return _git(repository, "mktree", "-z", data="".join(entries).encode("utf-8"))


def _commit(repository: Path, files: dict[str, bytes]) -> str:
    return _git(repository, "commit-tree", _tree(repository, files), data=b"path identities\n")


@pytest.mark.parametrize(
    "paths",
    [
        pytest.param(("A/one.py", "a/two.py"), id="case-prefix"),
        pytest.param(("src/Foo/a.py", "src/foo/b.py"), id="nested-case-prefix"),
        pytest.param(("caf\u00e9/one.py", "cafe\u0301/two.py"), id="unicode-prefix"),
        pytest.param(("Foo", "foo/bar.py"), id="file-directory-alias"),
    ],
)
@pytest.mark.parametrize("invalid_side", ["before", "after"])
def test_prefix_collision_rejected_before_either_tree_is_materialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    paths: tuple[str, str],
    invalid_side: str,
) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    valid = _commit(repository, {"safe.py": b"valid = True\n"})
    invalid = _commit(repository, {paths[0]: b"one = 1\n", paths[1]: b"two = 2\n"})
    before, after = (invalid, valid) if invalid_side == "before" else (valid, invalid)

    def forbidden_workspace_creation(*args: object, **kwargs: object) -> str:
        pytest.fail("neither snapshot may be created before both path sets are validated")

    monkeypatch.setattr(
        "thebigdiffer.repository.git.tempfile.mkdtemp", forbidden_workspace_creation
    )
    with pytest.raises(GitPreparationError, match="case or Unicode-normalization path collision"):
        GitRepositoryPreparer(repository, before, after).prepare()


def test_shared_directory_prefix_preserves_paths_bytes_and_manifest(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    files = {"A/one.py": b"one = 1\n", "A/two.py": b"two = 2\n"}
    commit = _commit(repository, files)

    with GitRepositoryPreparer(repository, commit, commit).prepare() as prepared:
        for version, root in (
            ("before", prepared.before_directory),
            ("after", prepared.after_directory),
        ):
            assert {path: root.joinpath(path).read_bytes() for path in files} == files
            record = prepared.preparation.serializable()[version]
            assert [entry["path"] for entry in record["entries"]] == sorted(files)
            assert [entry.path for entry in inventory_tree(root, version).files] == sorted(files)
            assert record["materialization_status"] == "complete"
