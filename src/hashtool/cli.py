"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from hashtool.manifest import (
    DEFAULT_MANIFEST_NAME,
    build_manifest,
    scan,
    write_manifest,
)

EXIT_OK = 0
EXIT_ERROR = 1


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


class Progress:
    """Single-line progress on a terminal; silent otherwise (CI, pipes)."""

    def __init__(self, stream: TextIO, interval: float = 0.1) -> None:
        self.stream = stream
        self.enabled = stream.isatty()
        self.interval = interval
        self._last = 0.0
        self._shown = False

    def __call__(self, files: int, total_bytes: int) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if now - self._last < self.interval:
            return
        self._last = now
        self._shown = True
        self.stream.write(f"\rScanning: {files} files, {format_size(total_bytes)}")
        self.stream.flush()

    def finish(self) -> None:
        if self._shown:
            self.stream.write("\r\033[K")
            self.stream.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hashtool",
        description="Create SHA-256 manifests of directory trees and verify files against them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="hash a directory tree and write a manifest")
    p_scan.add_argument("directory", type=Path, help="directory to scan")
    p_scan.add_argument(
        "-o",
        "--output",
        type=Path,
        help=f"manifest file (default: DIRECTORY/{DEFAULT_MANIFEST_NAME})",
    )
    p_scan.add_argument("--force", action="store_true", help="overwrite an existing manifest")
    p_scan.add_argument(
        "-e",
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="glob pattern to exclude (repeatable); trailing '/' matches directories only",
    )
    p_scan.add_argument(
        "--follow-symlinks", action="store_true", help="follow symbolic links and junctions"
    )
    p_scan.add_argument("--no-progress", action="store_true", help="disable progress output")
    p_scan.set_defaults(func=cmd_scan)
    return parser


def cmd_scan(args: argparse.Namespace) -> int:
    root: Path = args.directory
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return EXIT_ERROR

    output: Path = args.output if args.output is not None else root / DEFAULT_MANIFEST_NAME
    if output.exists() and not args.force:
        print(f"error: {output} exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_ERROR

    progress = Progress(sys.stderr)
    progress.enabled = progress.enabled and not args.no_progress
    try:
        result = scan(
            root,
            exclude=args.exclude,
            exclude_paths=[output],
            follow_symlinks=args.follow_symlinks,
            progress=progress,
        )
    finally:
        progress.finish()

    for rel, message in result.errors:
        print(f"warning: skipped {rel}: {message}", file=sys.stderr)

    try:
        write_manifest(output, build_manifest(result.files), force=args.force)
    except OSError as exc:
        print(f"error: cannot write {output}: {exc}", file=sys.stderr)
        return EXIT_ERROR

    total = sum(int(entry["size"]) for entry in result.files.values())
    print(
        f"Wrote {output}: {len(result.files)} files, {format_size(total)}"
        + (f", {len(result.errors)} skipped" if result.errors else "")
    )
    return EXIT_ERROR if result.errors else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
