"""Scan directory trees and build, write and read SHA-256 manifests."""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

FORMAT_VERSION = 1
ALGORITHM = "sha256"
DEFAULT_MANIFEST_NAME = "hashtool-manifest.json"

FileEntry = dict[str, str | int]
ProgressCallback = Callable[[int, int], None]


@dataclass
class ScanResult:
    """Result of a scan: hashed files plus files that could not be processed."""

    files: dict[str, FileEntry] = field(default_factory=dict)
    errors: list[tuple[str, str]] = field(default_factory=list)


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


def scan(
    root: str | os.PathLike[str],
    *,
    exclude: Iterable[str] = (),
    exclude_paths: Iterable[str | os.PathLike[str]] = (),
    follow_symlinks: bool = False,
    progress: ProgressCallback | None = None,
) -> ScanResult:
    """Hash all regular files below root.

    Keys are paths relative to root in "/" notation. Empty directories are
    ignored implicitly. Symlinks (and Windows junctions) are skipped unless
    follow_symlinks is set; directory loops are detected in that case.
    Files that cannot be read are recorded in ScanResult.errors.
    """
    root_path = Path(root)
    patterns = tuple(exclude)
    skip_paths = {Path(p).resolve() for p in exclude_paths}
    result = ScanResult()
    total_bytes = 0

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
                digest = hash_file(entry.path)
            except OSError as exc:
                result.errors.append((rel, str(exc)))
                continue

            result.files[rel] = {"hash": digest, "size": size}
            total_bytes += size
            if progress is not None:
                progress(len(result.files), total_bytes)

    return result


def build_manifest(files: dict[str, FileEntry], now: datetime | None = None) -> dict:
    """Wrap scanned files with metadata."""
    if now is None:
        now = datetime.now(UTC)
    created = now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "format_version": FORMAT_VERSION,
        "algorithm": ALGORITHM,
        "created": created,
        "files": dict(sorted(files.items())),
    }


def write_manifest(path: str | os.PathLike[str], manifest: dict, *, force: bool = False) -> None:
    """Write the manifest as UTF-8 JSON.

    Raises FileExistsError if the file exists and force is not set.
    """
    mode = "w" if force else "x"
    with open(path, mode, encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def read_manifest(path: str | os.PathLike[str]) -> dict:
    """Read a manifest written by write_manifest."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
