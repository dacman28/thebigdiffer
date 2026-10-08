from __future__ import annotations

import codecs
import errno
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from thebigdiffer.provenance import (
    EvidenceProvenance,
    InventoryProducer,
    make_content_id,
)

Version = Literal["before", "after"]
IngestStatus = Literal["inventoried", "skipped", "error"]

LANGUAGES = {
    ".c": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".cxx": "C++",
    ".h": "C/C++ header",
    ".hpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".php": "PHP",
    ".pl": "Perl",
    ".py": "Python",
    ".pyi": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sh": "Shell",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
}

_READ_FLAGS = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY_FLAGS = _READ_FLAGS | getattr(os, "O_DIRECTORY", 0)
_CHUNK_SIZE = 1024 * 1024
_PREFIX_SIZE = 8192


class IngestionError(ValueError):
    """Raised when a tree root cannot be inventoried safely."""


@dataclass(frozen=True)
class IngestionLimits:
    max_entries: int = 100_000
    max_file_bytes: int = 2 * 1024 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if min(self.max_entries, self.max_file_bytes, self.max_total_bytes) <= 0:
            raise ValueError("ingestion limits must be greater than zero")


@dataclass(frozen=True)
class FileRecord:
    evidence_id: str
    version: Version
    path: str
    file_kind: str
    language: str | None
    size: int | None
    sha256: str | None
    ingest_status: IngestStatus
    issue: str | None
    link_target: str | None
    provenance: EvidenceProvenance


@dataclass(frozen=True)
class IngestDiagnostic:
    evidence_id: str
    path: str
    status: Literal["skipped", "error"]
    reason: str
    provenance: EvidenceProvenance


@dataclass(frozen=True)
class PackageInventory:
    version: Version
    root_hash: str
    file_count: int
    total_size: int
    files: tuple[FileRecord, ...]
    ingest_diagnostics: tuple[IngestDiagnostic, ...]


@dataclass(frozen=True)
class TextReadResult:
    status: Literal["available", "not_text", "too_large", "failed"]
    text: str | None
    error: str | None = None


@dataclass
class _InventoryState:
    version: Version
    limits: IngestionLimits
    files: list[FileRecord]
    diagnostics: list[IngestDiagnostic]
    entries_seen: int = 0
    bytes_accepted: int = 0
    limit_reported: bool = False


def normalize_relative_path(value: str | os.PathLike[str]) -> str:
    """Normalize a user-supplied relative label to slash-separated form."""

    raw = os.fspath(value).replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValueError(f"unsafe relative path: {raw!r}")
    if len(raw) >= 2 and raw[1] == ":" and raw[0].isalpha():
        raise ValueError(f"unsafe relative path: {raw!r}")
    parts = raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe relative path: {raw!r}")
    return "/".join(parts)


def inventory_tree(
    root: Path,
    version: Version,
    limits: IngestionLimits | None = None,
) -> PackageInventory:
    """Inventory a directory without following links or executing its contents."""

    if not _secure_traversal_supported():
        raise IngestionError(
            "platform lacks the directory-relative no-follow operations required for safe ingest"
        )
    configured = limits or IngestionLimits()
    supplied_root = root.expanduser()
    try:
        root_stat = supplied_root.lstat()
    except OSError as error:
        raise IngestionError(f"cannot inspect input root: {_stable_os_error(error)}") from error
    if stat.S_ISLNK(root_stat.st_mode):
        raise IngestionError("input root must not be a symlink")
    if not stat.S_ISDIR(root_stat.st_mode):
        raise IngestionError("input root must be a directory")

    try:
        root_fd = os.open(supplied_root, _DIRECTORY_FLAGS)
    except OSError as error:
        raise IngestionError(f"cannot open input root: {_stable_os_error(error)}") from error
    try:
        opened_root_stat = os.fstat(root_fd)
    except OSError as error:
        os.close(root_fd)
        raise IngestionError(f"cannot verify input root: {_stable_os_error(error)}") from error
    if not _same_object(root_stat, opened_root_stat):
        os.close(root_fd)
        raise IngestionError("input root changed while it was being opened")

    state = _InventoryState(version, configured, [], [])
    try:
        _scan_directory(root_fd, (), state)
    finally:
        os.close(root_fd)

    state.files.sort(key=lambda item: item.path)
    state.diagnostics.sort(key=lambda item: (item.path, item.status, item.reason))
    root_hash = _tree_hash(state.files, state.diagnostics)
    return PackageInventory(
        version=version,
        root_hash=root_hash,
        file_count=len(state.files),
        total_size=sum(item.size or 0 for item in state.files),
        files=tuple(state.files),
        ingest_diagnostics=tuple(state.diagnostics),
    )


def _scan_directory(directory_fd: int, parts: tuple[str, ...], state: _InventoryState) -> None:
    if state.entries_seen >= state.limits.max_entries:
        _record_entry_limit(parts, state)
        return
    try:
        with os.scandir(directory_fd) as iterator:
            remaining = state.limits.max_entries - state.entries_seen
            entries: list[os.DirEntry[str]] = []
            for entry in iterator:
                if len(entries) >= remaining:
                    _record_entry_limit(parts, state)
                    state.entries_seen = state.limits.max_entries
                    return
                entries.append(entry)
            entries.sort(key=lambda item: item.name)
    except OSError as error:
        _add_diagnostic(
            state,
            _path_label(parts),
            "error",
            f"directory unreadable: {_stable_os_error(error)}",
        )
        return

    for entry in entries:
        if state.entries_seen >= state.limits.max_entries:
            _record_entry_limit(parts, state)
            return
        state.entries_seen += 1
        child_parts = (*parts, entry.name)
        if "\\" in entry.name or entry.name in {"", ".", ".."}:
            _add_diagnostic(
                state,
                _path_label(child_parts, escape=True),
                "skipped",
                "path component cannot be represented as a normalized relative path",
            )
            continue
        relative = _path_label(child_parts)
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError as error:
            state.files.append(
                _make_file_record(
                    state.version,
                    relative,
                    "unreadable",
                    None,
                    None,
                    None,
                    "error",
                    _stable_os_error(error),
                )
            )
            continue

        if stat.S_ISLNK(metadata.st_mode):
            _record_symlink(directory_fd, entry.name, relative, state)
        elif stat.S_ISDIR(metadata.st_mode):
            _scan_child_directory(directory_fd, entry.name, child_parts, metadata, state)
        elif stat.S_ISREG(metadata.st_mode):
            _record_regular_file(directory_fd, entry.name, relative, metadata, state)
        else:
            state.files.append(
                _make_file_record(
                    state.version,
                    relative,
                    "unsupported",
                    None,
                    metadata.st_size,
                    None,
                    "skipped",
                    f"unsupported filesystem object: {_mode_kind(metadata.st_mode)}",
                )
            )


def _scan_child_directory(
    parent_fd: int,
    name: str,
    parts: tuple[str, ...],
    expected_metadata: os.stat_result,
    state: _InventoryState,
) -> None:
    child_fd = -1
    try:
        child_fd = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        opened_metadata = os.fstat(child_fd)
    except OSError as error:
        if child_fd >= 0:
            os.close(child_fd)
        _add_diagnostic(
            state,
            _path_label(parts),
            "error",
            f"directory not opened: {_stable_os_error(error)}",
        )
        return
    if not _same_object(expected_metadata, opened_metadata):
        os.close(child_fd)
        _add_diagnostic(
            state,
            _path_label(parts),
            "error",
            "directory changed while it was being opened",
        )
        return
    try:
        _scan_directory(child_fd, parts, state)
    finally:
        os.close(child_fd)


def _record_symlink(parent_fd: int, name: str, relative: str, state: _InventoryState) -> None:
    try:
        target = os.readlink(name, dir_fd=parent_fd)
        target_bytes = os.fsencode(target)
        digest = hashlib.sha256(target_bytes).hexdigest()
        size = len(target_bytes)
        issue = "symlink not followed"
        status: IngestStatus = "skipped"
    except OSError as error:
        target = None
        digest = None
        size = None
        issue = f"symlink target unreadable: {_stable_os_error(error)}"
        status = "error"
    state.files.append(
        _make_file_record(
            state.version,
            relative,
            "symlink",
            None,
            size,
            digest,
            status,
            issue,
            link_target=target,
        )
    )


def _record_regular_file(
    parent_fd: int,
    name: str,
    relative: str,
    metadata: os.stat_result,
    state: _InventoryState,
) -> None:
    if metadata.st_size > state.limits.max_file_bytes:
        state.files.append(
            _make_file_record(
                state.version,
                relative,
                "unreadable",
                None,
                metadata.st_size,
                None,
                "skipped",
                "file exceeds max_file_bytes",
            )
        )
        return
    if state.bytes_accepted + metadata.st_size > state.limits.max_total_bytes:
        state.files.append(
            _make_file_record(
                state.version,
                relative,
                "unreadable",
                None,
                metadata.st_size,
                None,
                "skipped",
                "tree exceeds max_total_bytes",
            )
        )
        return

    try:
        descriptor = os.open(name, _READ_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        state.files.append(
            _make_file_record(
                state.version,
                relative,
                "unreadable",
                None,
                metadata.st_size,
                None,
                "error",
                _stable_os_error(error),
            )
        )
        return

    digest = hashlib.sha256()
    prefix = bytearray()
    utf8_decoder = codecs.getincrementaldecoder("utf-8")()
    is_utf8 = True
    has_nul = False
    bytes_read = 0
    try:
        opened_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(opened_metadata.st_mode):
            raise OSError(errno.EINVAL, "opened object is not a regular file")
        if not _same_object(metadata, opened_metadata):
            raise OSError(errno.EIO, "file changed while it was being opened")
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                bytes_read += len(chunk)
                if (
                    bytes_read > state.limits.max_file_bytes
                    or state.bytes_accepted + bytes_read > state.limits.max_total_bytes
                ):
                    raise OSError(errno.EFBIG, "file exceeded configured byte limit while hashing")
                digest.update(chunk)
                if len(prefix) < _PREFIX_SIZE:
                    prefix.extend(chunk[: _PREFIX_SIZE - len(prefix)])
                has_nul = has_nul or b"\x00" in chunk
                if is_utf8:
                    try:
                        utf8_decoder.decode(chunk)
                    except UnicodeDecodeError:
                        is_utf8 = False
            if is_utf8:
                try:
                    utf8_decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    is_utf8 = False
            final_metadata = os.fstat(stream.fileno())
        if bytes_read != opened_metadata.st_size or not _same_file_state(
            opened_metadata, final_metadata
        ):
            raise OSError(errno.EIO, "file changed while hashing")
    except OSError as error:
        if descriptor >= 0:
            os.close(descriptor)
        state.files.append(
            _make_file_record(
                state.version,
                relative,
                "unreadable",
                None,
                metadata.st_size,
                None,
                "error",
                _stable_os_error(error),
            )
        )
        return

    state.bytes_accepted += bytes_read
    language = _language(relative, bytes(prefix))
    file_kind = _classify_file(bytes(prefix), is_utf8 and not has_nul, language)
    state.files.append(
        _make_file_record(
            state.version,
            relative,
            file_kind,
            language if file_kind == "source" else None,
            bytes_read,
            digest.hexdigest(),
            "inventoried",
            None,
        )
    )


def read_inventoried_text(root: Path, record: FileRecord, max_bytes: int) -> TextReadResult:
    """Read a text record beneath ``root`` and verify it still matches inventory."""

    if record.ingest_status != "inventoried" or record.file_kind not in {"source", "text"}:
        return TextReadResult("not_text", None)
    if record.size is None or record.size > max_bytes:
        return TextReadResult(
            "too_large", None, f"source exceeds {max_bytes} byte diff/parser limit"
        )

    try:
        descriptor = _open_beneath(root, record.path)
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            data = stream.read(max_bytes + 1)
    except OSError as error:
        return TextReadResult("failed", None, _stable_os_error(error))
    if len(data) > max_bytes:
        return TextReadResult(
            "too_large", None, f"source exceeds {max_bytes} byte diff/parser limit"
        )
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != record.size or digest != record.sha256:
        return TextReadResult("failed", None, "file changed after inventory")
    if b"\x00" in data:
        return TextReadResult("failed", None, "inventoried text contains a NUL byte")
    try:
        return TextReadResult("available", data.decode("utf-8"))
    except UnicodeDecodeError:
        return TextReadResult("failed", None, "inventoried text is not valid UTF-8")


def _open_beneath(root: Path, relative: str) -> int:
    parts = normalize_relative_path(relative).split("/")
    descriptors: list[int] = []
    try:
        descriptors.append(os.open(root, _DIRECTORY_FLAGS))
        for part in parts[:-1]:
            descriptors.append(os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptors[-1]))
        file_fd = os.open(parts[-1], _READ_FLAGS, dir_fd=descriptors[-1])
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            os.close(file_fd)
            raise OSError(errno.EINVAL, "inventoried path is no longer a regular file")
        return file_fd
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _make_file_record(
    version: Version,
    path: str,
    file_kind: str,
    language: str | None,
    size: int | None,
    sha256: str | None,
    ingest_status: IngestStatus,
    issue: str | None,
    *,
    link_target: str | None = None,
) -> FileRecord:
    producer = InventoryProducer.TREE_INVENTORY
    material = {
        "version": version,
        "path": path,
        "file_kind": file_kind,
        "language": language,
        "size": size,
        "sha256": sha256,
        "ingest_status": ingest_status,
        "issue": issue,
        "link_target": link_target,
    }
    return FileRecord(
        evidence_id=make_content_id("file", producer.value, material),
        version=version,
        path=path,
        file_kind=file_kind,
        language=language,
        size=size,
        sha256=sha256,
        ingest_status=ingest_status,
        issue=issue,
        link_target=link_target,
        provenance=EvidenceProvenance(producer.value),
    )


def _add_diagnostic(
    state: _InventoryState,
    path: str,
    status: Literal["skipped", "error"],
    reason: str,
) -> None:
    producer = InventoryProducer.TREE_DIAGNOSTIC
    material = {"version": state.version, "path": path, "status": status, "reason": reason}
    state.diagnostics.append(
        IngestDiagnostic(
            evidence_id=make_content_id("fact", producer.value, material),
            path=path,
            status=status,
            reason=reason,
            provenance=EvidenceProvenance(producer.value),
        )
    )


def _record_entry_limit(parts: tuple[str, ...], state: _InventoryState) -> None:
    if not state.limit_reported:
        _add_diagnostic(
            state,
            _path_label(parts),
            "skipped",
            f"entry traversal stopped at max_entries={state.limits.max_entries}",
        )
        state.limit_reported = True


def _tree_hash(files: list[FileRecord], diagnostics: list[IngestDiagnostic]) -> str:
    material = {
        "files": [
            {
                "path": item.path,
                "file_kind": item.file_kind,
                "language": item.language,
                "size": item.size,
                "sha256": item.sha256,
                "ingest_status": item.ingest_status,
                "issue": item.issue,
                "link_target": item.link_target,
            }
            for item in files
        ],
        "diagnostics": [
            {"path": item.path, "status": item.status, "reason": item.reason}
            for item in diagnostics
        ],
    }
    encoded = json.dumps(material, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _classify_file(
    prefix: bytes,
    is_text: bool,
    language: str | None,
) -> str:
    if prefix.startswith(b"\x7fELF"):
        return "native-binary-elf"
    if prefix[:4] in {
        b"\xfe\xed\xfa\xce",
        b"\xce\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xcf\xfa\xed\xfe",
        b"\xca\xfe\xba\xbe",
    }:
        return "native-binary-mach-o"
    if prefix.startswith(b"MZ"):
        return "native-binary-pe"
    if prefix.startswith(b"\x00asm"):
        return "bytecode-wasm"
    if not is_text:
        return "binary"
    if language is not None:
        return "source"
    return "text"


def _language(relative: str, prefix: bytes) -> str | None:
    language = LANGUAGES.get(Path(relative).suffix.lower())
    if language is not None:
        return language
    first_line = prefix.splitlines()[0].lower() if prefix else b""
    if first_line.startswith(b"#!"):
        if b"python" in first_line:
            return "Python"
        if any(name in first_line for name in (b"node", b"deno")):
            return "JavaScript"
        if any(name in first_line for name in (b"/sh", b"bash", b"zsh")):
            return "Shell"
    return None


def _mode_kind(mode: int) -> str:
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISCHR(mode):
        return "character-device"
    if stat.S_ISBLK(mode):
        return "block-device"
    return "unknown"


def _path_label(parts: tuple[str, ...], *, escape: bool = False) -> str:
    if not parts:
        return "."
    if escape:
        safe = (part.replace("%", "%25").replace("\\", "%5C") for part in parts)
        return "/".join(safe)
    return "/".join(parts)


def _stable_os_error(error: OSError) -> str:
    number = error.errno if error.errno is not None else "unknown"
    message = error.strerror or error.__class__.__name__
    return f"OS error {number}: {message}"


def _secure_traversal_supported() -> bool:
    return (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and os.open in os.supports_dir_fd
        and os.readlink in os.supports_dir_fd
        and os.scandir in os.supports_fd
    )


def _same_object(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        first.st_dev == second.st_dev
        and first.st_ino == second.st_ino
        and stat.S_IFMT(first.st_mode) == stat.S_IFMT(second.st_mode)
    )


def _same_file_state(first: os.stat_result, second: os.stat_result) -> bool:
    return (
        _same_object(first, second)
        and first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
        and first.st_ctime_ns == second.st_ctime_ns
    )
