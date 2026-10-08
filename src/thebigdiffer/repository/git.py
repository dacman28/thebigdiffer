"""Exact, no-checkout materialization of local committed Git trees."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from dataclasses import asdict
from pathlib import Path
from typing import Any

from thebigdiffer.ingest import normalize_relative_path
from thebigdiffer.repository.model import (
    GitPreparationLimits,
    PreparedGitRepository,
    SourcePreparation,
)

PREPARATION_VERSION = "thebigdiffer.git-object-snapshot.v1"
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_CREATE_FILE_FLAGS = (
    os.O_RDWR
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_NOFOLLOW", 0)
)
_OBJECT_ID = re.compile(r"^[0-9a-f]+$")


class GitPreparationError(ValueError):
    """A deterministic failure while resolving or materializing committed Git objects."""


class GitRepositoryPreparer:
    """Prepare exact BEFORE and AFTER source directories from local Git objects."""

    def __init__(
        self,
        repository: Path,
        before_ref: str,
        after_ref: str,
        *,
        limits: GitPreparationLimits | None = None,
        git_executable: str | None = None,
    ) -> None:
        self._supplied_repository = repository
        self.before_ref = _validate_ref(before_ref, "before_ref")
        self.after_ref = _validate_ref(after_ref, "after_ref")
        self.limits = limits or GitPreparationLimits()
        executable = git_executable or shutil.which("git")
        if executable is None:
            raise GitPreparationError("Git executable is unavailable")
        self.git_executable = executable
        self.repository = self._resolve_repository(repository)
        self._environment = _git_environment()

    def prepare(self) -> PreparedGitRepository:
        """Resolve refs and materialize both snapshots in a new private temporary root."""
        snapshot_root = Path(tempfile.mkdtemp(prefix="thebigdiffer-git-"))
        os.chmod(snapshot_root, 0o700)
        before_directory = snapshot_root / "before"
        after_directory = snapshot_root / "after"
        before_directory.mkdir(mode=0o700)
        after_directory.mkdir(mode=0o700)
        try:
            repository_record = self._repository_record()
            before = self._resolve_and_materialize(
                supplied_ref=self.before_ref,
                snapshot_root=before_directory,
            )
            after = self._resolve_and_materialize(
                supplied_ref=self.after_ref,
                snapshot_root=after_directory,
            )
            metadata = {
                "snapshot_preparation_version": PREPARATION_VERSION,
                "materialization_status": "complete",
                "object_semantics": {
                    "working_tree_used": False,
                    "checkout_filters_applied": False,
                    "archive_attributes_applied": False,
                    "submodules_initialized": False,
                    "git_lfs_downloaded": False,
                    "network_allowed": False,
                },
                "repository": repository_record,
                "before": before,
                "after": after,
                "counts": {
                    key: before["counts"][key] + after["counts"][key]
                    for key in before["counts"]
                },
                "limits": asdict(self.limits),
            }
            return PreparedGitRepository(
                snapshot_root=snapshot_root,
                before_directory=before_directory,
                after_directory=after_directory,
                preparation=SourcePreparation.git(metadata),
            )
        except BaseException:
            shutil.rmtree(snapshot_root)
            raise

    def _resolve_repository(self, repository: Path) -> Path:
        try:
            resolved = repository.expanduser().resolve(strict=True)
        except OSError as error:
            raise GitPreparationError(f"cannot inspect Git repository path: {error}") from error
        if not resolved.is_dir():
            raise GitPreparationError("Git repository path must be a directory")
        if any(character in str(resolved) for character in ("\0", "\r", "\n")):
            raise GitPreparationError("Git repository path contains an unsafe control character")
        try:
            str(resolved).encode("utf-8", errors="strict")
        except UnicodeEncodeError as error:
            raise GitPreparationError("Git repository path is not valid UTF-8") from error
        return resolved

    def _repository_record(self) -> dict[str, Any]:
        version = self._run_text("--version").strip()
        try:
            git_directory = _single_git_line(
                self._run_text("rev-parse", "--absolute-git-dir"),
                "absolute Git directory",
            )
            object_format = self._run_text(
                "rev-parse", "--show-object-format=storage"
            ).strip()
        except GitPreparationError as error:
            raise GitPreparationError(
                f"path is not a usable local Git repository: {self.repository}"
            ) from error
        if not git_directory or not object_format:
            raise GitPreparationError("Git repository identity is incomplete")
        repository_path = str(self.repository)
        git_directory_path = str(Path(git_directory).resolve(strict=False))
        identity_material = f"{repository_path}\0{git_directory_path}\0{object_format}".encode()
        return {
            "path": repository_path,
            "path_sha256": hashlib.sha256(os.fsencode(repository_path)).hexdigest(),
            "git_directory": git_directory_path,
            "identity_kind": "canonical_path_and_git_directory",
            "identity_sha256": hashlib.sha256(identity_material).hexdigest(),
            "object_format": object_format,
            "git_version": version,
            "local_only": True,
        }

    def _resolve_and_materialize(
        self,
        *,
        supplied_ref: str,
        snapshot_root: Path,
    ) -> dict[str, Any]:
        commit = self._resolve_commit(supplied_ref)
        tree = self._resolve_tree(commit)
        entries = self._enumerate_tree(tree)
        records = self._materialize_entries(entries, snapshot_root)
        counts = {
            "file_count": len(records),
            "regular_file_count": sum(item["kind"] == "regular" for item in records),
            "symlink_count": sum(item["kind"] == "symlink" for item in records),
            "gitlink_count": sum(item["kind"] == "gitlink" for item in records),
            "unsupported_entry_count": sum(
                item["kind"] == "unsupported" for item in records
            ),
            "materialized_entry_count": sum(
                item["status"] == "materialized" for item in records
            ),
        }
        return {
            "supplied_ref": supplied_ref,
            "resolved_commit_sha": commit,
            "tree_sha": tree,
            "counts": counts,
            "entries": records,
            "materialization_status": "complete",
        }

    def _resolve_commit(self, supplied_ref: str) -> str:
        expression = f"{supplied_ref}^{{commit}}"
        try:
            commit = self._run_text(
                "rev-parse", "--verify", "--end-of-options", expression
            ).strip()
        except GitPreparationError as error:
            raise GitPreparationError(
                f"Git ref does not resolve to a commit: {supplied_ref!r}"
            ) from error
        self._validate_object_id(commit, "resolved commit")
        object_type = self._run_text("cat-file", "-t", commit).strip()
        if object_type != "commit":
            raise GitPreparationError(
                f"Git ref did not resolve to a commit object: {supplied_ref!r}"
            )
        return commit

    def _resolve_tree(self, commit: str) -> str:
        tree = self._run_text(
            "rev-parse", "--verify", "--end-of-options", f"{commit}^{{tree}}"
        ).strip()
        self._validate_object_id(tree, "resolved tree")
        if self._run_text("cat-file", "-t", tree).strip() != "tree":
            raise GitPreparationError("resolved commit tree is not a tree object")
        return tree

    def _validate_object_id(self, value: str, label: str) -> None:
        if not _OBJECT_ID.fullmatch(value) or len(value) not in {40, 64}:
            raise GitPreparationError(f"{label} has an invalid object ID")

    def _enumerate_tree(self, tree: str) -> list[dict[str, str]]:
        output = self._run_bytes("ls-tree", "-rz", "--full-tree", "-r", tree)
        entries = _parse_ls_tree(output)
        if len(entries) > self.limits.max_entries:
            raise GitPreparationError(
                f"committed tree exceeds max_entries={self.limits.max_entries}"
            )
        _validate_entry_paths(entries)
        return sorted(entries, key=lambda item: item["path"].encode("utf-8"))

    def _materialize_entries(
        self,
        entries: list[dict[str, str]],
        snapshot_root: Path,
    ) -> list[dict[str, Any]]:
        if any(snapshot_root.iterdir()):
            raise GitPreparationError("snapshot root collision: assigned root is not empty")
        root_fd = os.open(snapshot_root, _DIRECTORY_FLAGS)
        total_bytes = 0
        records: list[dict[str, Any]] = []
        try:
            for entry in entries:
                mode = entry["mode"]
                object_type = entry["object_type"]
                object_id = entry["object_id"]
                path = entry["path"]
                base: dict[str, Any] = {
                    "path": path,
                    "mode": mode,
                    "object_type": object_type,
                    "object_id": object_id,
                }
                if mode in {"100644", "100755"}:
                    if object_type != "blob":
                        raise GitPreparationError(
                            f"regular-file mode has non-blob object at {path!r}"
                        )
                    size = self._object_size(object_id)
                    total_bytes = self._admit_blob(path, size, total_bytes)
                    digest = self._materialize_regular(
                        root_fd,
                        path,
                        object_id,
                        executable=mode == "100755",
                        expected_size=size,
                    )
                    records.append(
                        {
                            **base,
                            "kind": "regular",
                            "status": "materialized",
                            "size": size,
                            "sha256": digest,
                            "executable": mode == "100755",
                        }
                    )
                elif mode == "120000":
                    if object_type != "blob":
                        raise GitPreparationError(
                            f"symlink mode has non-blob object at {path!r}"
                        )
                    size = self._object_size(object_id)
                    if size > self.limits.max_symlink_target_bytes:
                        raise GitPreparationError(
                            f"symlink target at {path!r} exceeds "
                            f"max_symlink_target_bytes={self.limits.max_symlink_target_bytes}"
                        )
                    total_bytes = self._admit_blob(path, size, total_bytes)
                    target = self._run_bytes("cat-file", "blob", object_id)
                    if len(target) != size:
                        raise GitPreparationError(
                            f"Git symlink object changed while reading {path!r}"
                        )
                    if b"\0" in target:
                        raise GitPreparationError(f"Git symlink target contains NUL at {path!r}")
                    self._materialize_symlink(root_fd, path, target)
                    records.append(
                        {
                            **base,
                            "kind": "symlink",
                            "status": "materialized",
                            "size": size,
                            "sha256": hashlib.sha256(target).hexdigest(),
                            "followed": False,
                        }
                    )
                elif mode == "160000":
                    if object_type != "commit":
                        raise GitPreparationError(
                            f"gitlink mode has unexpected object type at {path!r}"
                        )
                    records.append(
                        {
                            **base,
                            "kind": "gitlink",
                            "status": "skipped",
                            "reason": "submodule gitlink is not initialized or traversed",
                        }
                    )
                else:
                    records.append(
                        {
                            **base,
                            "kind": "unsupported",
                            "status": "skipped",
                            "reason": "unsupported Git tree mode",
                        }
                    )
        finally:
            os.close(root_fd)
        return records

    def _admit_blob(self, path: str, size: int, current_total: int) -> int:
        if size < 0:
            raise GitPreparationError(f"Git reported a negative object size for {path!r}")
        if size > self.limits.max_blob_bytes:
            raise GitPreparationError(
                f"blob at {path!r} exceeds max_blob_bytes={self.limits.max_blob_bytes}"
            )
        new_total = current_total + size
        if new_total > self.limits.max_total_bytes:
            raise GitPreparationError(
                f"snapshot exceeds max_total_bytes={self.limits.max_total_bytes}"
            )
        return new_total

    def _object_size(self, object_id: str) -> int:
        value = self._run_text("cat-file", "-s", object_id).strip()
        try:
            return int(value)
        except ValueError as error:
            raise GitPreparationError("Git returned a malformed object size") from error

    def _materialize_regular(
        self,
        root_fd: int,
        path: str,
        object_id: str,
        *,
        executable: bool,
        expected_size: int,
    ) -> str:
        parts = path.split("/")
        parent_fd = _open_parent(root_fd, parts[:-1])
        file_fd = -1
        try:
            file_fd = os.open(parts[-1], _CREATE_FILE_FLAGS, 0o600, dir_fd=parent_fd)
            command = self._command("cat-file", "blob", object_id)
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=file_fd,
                    stderr=subprocess.PIPE,
                    env=self._environment,
                )
            except OSError as error:
                raise GitPreparationError(f"cannot execute Git object read: {error}") from error
            _, stderr = process.communicate()
            if process.returncode != 0:
                raise GitPreparationError(
                    "Git object read failed: " + _stderr_text(stderr)
                )
            metadata = os.fstat(file_fd)
            if metadata.st_size != expected_size:
                raise GitPreparationError(
                    f"Git blob size changed while materializing {path!r}"
                )
            os.fchmod(file_fd, 0o755 if executable else 0o644)
            os.lseek(file_fd, 0, os.SEEK_SET)
            digest = hashlib.sha256()
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest()
        except Exception:
            try:
                os.unlink(parts[-1], dir_fd=parent_fd)
            except OSError:
                pass
            raise
        finally:
            if file_fd >= 0:
                os.close(file_fd)
            os.close(parent_fd)

    @staticmethod
    def _materialize_symlink(root_fd: int, path: str, target: bytes) -> None:
        parts = path.split("/")
        parent_fd = _open_parent(root_fd, parts[:-1])
        try:
            os.symlink(target, os.fsencode(parts[-1]), dir_fd=parent_fd)
        except (OSError, ValueError) as error:
            raise GitPreparationError(
                f"cannot materialize Git symlink at {path!r}: {error}"
            ) from error
        finally:
            os.close(parent_fd)

    def _command(self, *arguments: str) -> list[str]:
        return [
            self.git_executable,
            "--no-optional-locks",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(self.repository),
            *arguments,
        ]

    def _run_bytes(self, *arguments: str) -> bytes:
        command = self._command(*arguments)
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                env=self._environment,
            )
        except OSError as error:
            raise GitPreparationError(f"cannot execute Git: {error}") from error
        if completed.returncode != 0:
            raise GitPreparationError(
                f"Git command {arguments[0]!r} failed: {_stderr_text(completed.stderr)}"
            )
        return completed.stdout

    def _run_text(self, *arguments: str) -> str:
        output = self._run_bytes(*arguments)
        try:
            return output.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise GitPreparationError(
                f"Git command {arguments[0]!r} returned non-UTF-8 metadata"
            ) from error


def _git_environment() -> dict[str, str]:
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_PAGER": "cat",
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    return environment


def _validate_ref(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise GitPreparationError(f"{name} must be non-empty text of at most 4096 characters")
    if any(character in value for character in ("\0", "\r", "\n")):
        raise GitPreparationError(f"{name} contains an unsafe control character")
    return value


def _parse_ls_tree(output: bytes) -> list[dict[str, str]]:
    if output and not output.endswith(b"\0"):
        raise GitPreparationError("Git ls-tree output is not NUL terminated")
    entries: list[dict[str, str]] = []
    for raw_record in output.split(b"\0"):
        if not raw_record:
            continue
        try:
            raw_header, raw_path = raw_record.split(b"\t", 1)
            raw_mode, raw_type, raw_object = raw_header.split(b" ", 2)
            mode = raw_mode.decode("ascii", errors="strict")
            object_type = raw_type.decode("ascii", errors="strict")
            object_id = raw_object.decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as error:
            raise GitPreparationError("malformed or non-UTF-8 Git tree entry") from error
        if not re.fullmatch(r"[0-7]{6}", mode):
            raise GitPreparationError(f"malformed Git tree mode for {path!r}")
        if object_type not in {"blob", "commit"}:
            raise GitPreparationError(f"unsupported Git object type {object_type!r} at {path!r}")
        if not _OBJECT_ID.fullmatch(object_id) or len(object_id) not in {40, 64}:
            raise GitPreparationError(f"malformed Git object ID at {path!r}")
        entries.append(
            {
                "mode": mode,
                "object_type": object_type,
                "object_id": object_id,
                "path": path,
            }
        )
    return entries


def _validate_entry_paths(entries: list[dict[str, str]]) -> None:
    exact: set[str] = set()
    portable: dict[str, str] = {}
    for entry in entries:
        path = entry["path"]
        if "\0" in path or "\\" in path:
            raise GitPreparationError(f"unsafe Git tree path: {path!r}")
        try:
            normalized = normalize_relative_path(path)
        except ValueError as error:
            raise GitPreparationError(f"unsafe Git tree path: {path!r}") from error
        if normalized != path:
            raise GitPreparationError(f"ambiguous Git tree path: {path!r}")
        if path in exact:
            raise GitPreparationError(f"duplicate Git tree path: {path!r}")
        exact.add(path)
        key = unicodedata.normalize("NFC", path).casefold()
        previous = portable.get(key)
        if previous is not None and previous != path:
            raise GitPreparationError(
                f"case or Unicode-normalization path collision: {previous!r} and {path!r}"
            )
        portable[key] = path
    for path in exact:
        parts = path.split("/")
        for index in range(1, len(parts)):
            parent = "/".join(parts[:index])
            if parent in exact:
                raise GitPreparationError(
                    f"Git tree entry would traverse non-directory parent {parent!r}"
                )


def _open_parent(root_fd: int, parts: list[str]) -> int:
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current)
            except FileExistsError:
                pass
            child = os.open(part, _DIRECTORY_FLAGS, dir_fd=current)
            metadata = os.fstat(child)
            if not stat.S_ISDIR(metadata.st_mode):
                os.close(child)
                raise GitPreparationError("snapshot path parent is not a directory")
            os.close(current)
            current = child
        return current
    except Exception:
        os.close(current)
        raise


def _stderr_text(value: bytes | None) -> str:
    if value is None:
        return "unknown Git failure"
    text = value.decode("utf-8", errors="replace").strip()
    return text or "unknown Git failure"


def _single_git_line(value: str, label: str) -> str:
    line = value.removesuffix("\n").removesuffix("\r")
    if not line or "\n" in line or "\r" in line:
        raise GitPreparationError(f"Git returned malformed {label}")
    return line
