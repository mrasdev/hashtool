"""Scan directory trees, build and validate manifests, verify against them."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

FORMAT_VERSION = 1
ALGORITHM = "sha256"
DEFAULT_MANIFEST_NAME = "hashtool-manifest.json"

FileEntry = dict[str, str | int]
ProgressCallback = Callable[[int, int], None]


class ManifestError(Exception):
    """The manifest cannot be read or is not a valid, supported manifest."""


class Status(StrEnum):
    OK = "OK"
    CHANGED = "CHANGED"
    MISSING = "MISSING"
    NEW = "NEW"
    ERROR = "ERROR"


@dataclass
class ScanResult:
    """Result of a scan: hashed files plus files that could not be processed."""

    files: dict[str, FileEntry] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class WalkResult:
    """Regular files found below a root: relative path -> (absolute path, size)."""

    files: dict[str, tuple[str, int]] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class VerifyEntry:
    status: Status
    path: str
    message: str | None = None


@dataclass
class VerifyResult:
    """Non-OK entries sorted by path, plus counts for every status."""

    entries: list[VerifyEntry] = field(default_factory=list)
    counts: Counter[Status] = field(default_factory=Counter)

    @property
    def has_differences(self) -> bool:
        return any(self.counts[s] for s in (Status.CHANGED, Status.MISSING, Status.NEW))

    @property
    def has_errors(self) -> bool:
        return self.counts[Status.ERROR] > 0


def hash_file(path: str | os.PathLike[str]) -> str:
    """Return the hex digest of a file; file_digest reads it in blocks."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, ALGORITHM).hexdigest()


def is_excluded(rel_path: str, is_dir: bool, patterns: Iterable[str]) -> bool:
    """Check a relative POSIX path against glob patterns.

    A pattern matches the full relative path or the last path component.
    A pattern ending in "/" only matches directories.
    """
    name = rel_path.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/"):
            if not is_dir:
                continue
            pattern = pattern.rstrip("/")
        if fnmatch.fnmatchcase(rel_path, pattern) or fnmatch.fnmatchcase(name, pattern):
            return True
    return False


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def walk(
    root: str | os.PathLike[str],
    *,
    exclude: Iterable[str] = (),
    exclude_paths: Iterable[str | os.PathLike[str]] = (),
    follow_symlinks: bool = False,
) -> WalkResult:
    """Find all regular files below root without reading them.

    Keys are paths relative to root in "/" notation. Empty directories are
    ignored implicitly. Symlinks (and Windows junctions) are skipped unless
    follow_symlinks is set; directory loops are detected in that case.
    """
    root_path = Path(root)
    patterns = tuple(exclude)
    skip_paths = {Path(p).resolve() for p in exclude_paths}
    result = WalkResult()

    visited: set[tuple[int, int]] = set()
    root_stat = root_path.stat()
    visited.add((root_stat.st_dev, root_stat.st_ino))

    stack: list[tuple[Path, str]] = [(root_path, "")]
    while stack:
        dir_path, prefix = stack.pop()
        try:
            with os.scandir(dir_path) as it:
                entries = list(it)
        except OSError as exc:
            result.errors.append((prefix.rstrip("/") or ".", str(exc)))
            continue

        for entry in entries:
            rel = prefix + entry.name
            if _is_link(entry) and not follow_symlinks:
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=True)
                is_file = not is_dir and entry.is_file(follow_symlinks=True)
            except OSError as exc:
                result.errors.append((rel, str(exc)))
                continue

            if is_excluded(rel, is_dir, patterns):
                continue

            if is_dir:
                try:
                    st = os.stat(entry.path)
                except OSError as exc:
                    result.errors.append((rel, str(exc)))
                    continue
                key = (st.st_dev, st.st_ino)
                if key in visited:
                    continue  # symlink loop or directory reached twice
                visited.add(key)
                stack.append((Path(entry.path), rel + "/"))
                continue

            if not is_file:
                continue  # broken symlink, FIFO, device, socket ...

            if skip_paths and Path(entry.path).resolve() in skip_paths:
                continue

            try:
                size = os.stat(entry.path).st_size
            except OSError as exc:
                result.errors.append((rel, str(exc)))
                continue
            result.files[rel] = (entry.path, size)

    return result


def scan(
    root: str | os.PathLike[str],
    *,
    exclude: Iterable[str] = (),
    exclude_paths: Iterable[str | os.PathLike[str]] = (),
    follow_symlinks: bool = False,
    progress: ProgressCallback | None = None,
) -> ScanResult:
    """Hash all regular files below root (see walk for the selection rules).

    Files that cannot be read are recorded in ScanResult.errors.
    """
    found = walk(
        root, exclude=exclude, exclude_paths=exclude_paths, follow_symlinks=follow_symlinks
    )
    result = ScanResult(errors=list(found.errors))
    total_bytes = 0
    for rel, (path, size) in found.files.items():
        try:
            digest = hash_file(path)
        except OSError as exc:
            result.errors.append((rel, str(exc)))
            continue
        result.files[rel] = {"hash": digest, "size": size}
        total_bytes += size
        if progress is not None:
            progress(len(result.files), total_bytes)
    return result


def compare(
    stored: Mapping[str, FileEntry],
    current: Mapping[str, int],
    get_hash: Callable[[str], str],
    *,
    progress: ProgressCallback | None = None,
) -> VerifyResult:
    """Classify paths by comparing stored entries with current file sizes.

    stored maps paths to {"hash", "size"}; current maps paths to sizes.
    get_hash is only called for files present in both with equal size.
    OSError from get_hash results in Status.ERROR.
    """
    found: list[VerifyEntry] = []
    counts: Counter[Status] = Counter()
    processed = 0
    total_bytes = 0

    def add(status: Status, path: str, message: str | None = None) -> None:
        counts[status] += 1
        if status is not Status.OK:
            found.append(VerifyEntry(status, path, message))

    for path, size in current.items():
        expected = stored.get(path)
        if expected is None:
            add(Status.NEW, path)
        elif expected["size"] != size:
            add(Status.CHANGED, path)
        else:
            try:
                digest = get_hash(path)
            except OSError as exc:
                add(Status.ERROR, path, str(exc))
            else:
                add(Status.OK if digest == expected["hash"] else Status.CHANGED, path)
        processed += 1
        total_bytes += size
        if progress is not None:
            progress(processed, total_bytes)

    for path in stored.keys() - current.keys():
        add(Status.MISSING, path)

    found.sort(key=lambda e: e.path)
    return VerifyResult(entries=found, counts=counts)


def get_scan_options(manifest: Mapping) -> tuple[list[str], bool]:
    """Return (exclude, follow_symlinks) stored by scan, with defaults."""
    options = manifest.get("scan_options") or {}
    return list(options.get("exclude", [])), bool(options.get("follow_symlinks", False))


def verify(
    root: str | os.PathLike[str],
    manifest: Mapping,
    *,
    exclude_paths: Iterable[str | os.PathLike[str]] = (),
    progress: ProgressCallback | None = None,
) -> VerifyResult:
    """Compare the files below root with a loaded manifest.

    The scan options stored in the manifest (exclude, follow_symlinks) are
    applied, so files excluded at scan time are not reported as NEW.
    """
    exclude, follow_symlinks = get_scan_options(manifest)
    found = walk(
        root, exclude=exclude, exclude_paths=exclude_paths, follow_symlinks=follow_symlinks
    )
    current = {rel: size for rel, (_, size) in found.files.items()}
    result = compare(
        manifest["files"],
        current,
        lambda rel: hash_file(found.files[rel][0]),
        progress=progress,
    )
    for rel, message in found.errors:
        result.entries.append(VerifyEntry(Status.ERROR, rel, message))
        result.counts[Status.ERROR] += 1
    result.entries.sort(key=lambda e: e.path)
    return result


def build_manifest(
    files: dict[str, FileEntry],
    now: datetime | None = None,
    *,
    scan_options: Mapping | None = None,
) -> dict:
    """Wrap scanned files with metadata."""
    if now is None:
        now = datetime.now(UTC)
    created = now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    manifest = {
        "format_version": FORMAT_VERSION,
        "algorithm": ALGORITHM,
        "created": created,
        "files": dict(sorted(files.items())),
    }
    if scan_options is not None:
        manifest["scan_options"] = dict(scan_options)
    return manifest


def write_manifest(path: str | os.PathLike[str], manifest: dict, *, force: bool = False) -> None:
    """Write the manifest as UTF-8 JSON.

    Raises FileExistsError if the file exists and force is not set.
    """
    mode = "w" if force else "x"
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def read_manifest(path: str | os.PathLike[str]) -> dict:
    """Read a manifest written by write_manifest (no validation)."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_manifest(path: str | os.PathLike[str]) -> dict:
    """Read and validate a manifest. Raises ManifestError with a clear message."""
    try:
        data = read_manifest(path)
    except FileNotFoundError:
        raise ManifestError(f"manifest not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest is not valid JSON: {path}: {exc}") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from None

    if not isinstance(data, dict):
        raise ManifestError(f"manifest is not a JSON object: {path}")

    version = data.get("format_version")
    if version != FORMAT_VERSION:
        raise ManifestError(f"unsupported manifest format_version {version}")

    algorithm = data.get("algorithm")
    if algorithm != ALGORITHM:
        raise ManifestError(f"unsupported algorithm {algorithm!r}")

    files = data.get("files")
    if not isinstance(files, dict):
        raise ManifestError("manifest has no 'files' object")
    for rel, entry in files.items():
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("hash"), str)
            and isinstance(entry.get("size"), int)
            and not isinstance(entry.get("size"), bool)
        ):
            raise ManifestError(f"invalid entry {rel!r} in manifest")

    options = data.get("scan_options")
    if options is not None:
        exclude = options.get("exclude", []) if isinstance(options, dict) else None
        follow = options.get("follow_symlinks", False) if isinstance(options, dict) else None
        if not (
            isinstance(exclude, list)
            and all(isinstance(p, str) for p in exclude)
            and isinstance(follow, bool)
        ):
            raise ManifestError("invalid scan_options in manifest")

    return data
