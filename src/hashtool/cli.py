"""Command line interface."""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from hashtool import __version__
from hashtool.manifest import (
    DEFAULT_MANIFEST_NAME,
    ManifestError,
    Status,
    build_manifest,
    load_manifest,
    scan,
    verify,
    write_manifest,
)

# Same scheme as diff and cmp.
EXIT_OK = 0
EXIT_DIFFERENCES = 1
EXIT_ERROR = 2

STATUS_WIDTH = 7


def format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


class Progress:
    """Single-line progress on a terminal; silent otherwise (CI, pipes)."""

    def __init__(self, stream: TextIO, label: str = "Scanning", interval: float = 0.1) -> None:
        self.stream = stream
        self.label = label
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
        self.stream.write(f"\r{self.label}: {files} files, {format_size(total_bytes)}")
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
    parser.add_argument("--version", action="version", version=f"hashtool {__version__}")
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

    p_verify = sub.add_parser("verify", help="compare a directory tree with a manifest")
    p_verify.add_argument("directory", type=Path, help="directory to verify")
    p_verify.add_argument(
        "-m",
        "--manifest",
        type=Path,
        help=f"manifest file (default: DIRECTORY/{DEFAULT_MANIFEST_NAME})",
    )
    p_verify.add_argument("--no-progress", action="store_true", help="disable progress output")
    p_verify.set_defaults(func=cmd_verify)
    return parser


def error(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return EXIT_ERROR


def make_progress(label: str, disabled: bool) -> Progress:
    progress = Progress(sys.stderr, label)
    progress.enabled = progress.enabled and not disabled
    return progress


def cmd_scan(args: argparse.Namespace) -> int:
    root: Path = args.directory
    if not root.is_dir():
        return error(f"not a directory: {root}")

    output: Path = args.output if args.output is not None else root / DEFAULT_MANIFEST_NAME
    if output.exists() and not args.force:
        return error(f"{output} exists (use --force to overwrite)")

    progress = make_progress("Scanning", args.no_progress)
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

    scan_options = {"exclude": list(args.exclude), "follow_symlinks": args.follow_symlinks}
    try:
        write_manifest(
            output, build_manifest(result.files, scan_options=scan_options), force=args.force
        )
    except OSError as exc:
        return error(f"cannot write {output}: {exc}")

    total = sum(int(entry["size"]) for entry in result.files.values())
    print(
        f"Wrote {output}: {len(result.files)} files, {format_size(total)}"
        + (f", {len(result.errors)} skipped" if result.errors else "")
    )
    return EXIT_ERROR if result.errors else EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    root: Path = args.directory
    if not root.is_dir():
        return error(f"not a directory: {root}")

    manifest_path: Path = (
        args.manifest if args.manifest is not None else root / DEFAULT_MANIFEST_NAME
    )
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        return error(str(exc))

    progress = make_progress("Verifying", args.no_progress)
    try:
        result = verify(root, manifest, exclude_paths=[manifest_path], progress=progress)
    finally:
        progress.finish()

    for entry in result.entries:
        line = f"{entry.status.value:<{STATUS_WIDTH}}  {entry.path}"
        if entry.message:
            line += f": {entry.message}"
        print(line)

    counts = result.counts
    summary = (
        f"{counts[Status.OK]} ok, {counts[Status.CHANGED]} changed, "
        f"{counts[Status.MISSING]} missing, {counts[Status.NEW]} new"
    )
    if result.has_errors:
        summary += f", {counts[Status.ERROR]} errors"
    print(summary)

    if result.has_errors:
        return EXIT_ERROR
    return EXIT_DIFFERENCES if result.has_differences else EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
