import hashlib
import json
import os
from datetime import UTC, datetime, timedelta, timezone

import pytest

from hashtool import manifest
from hashtool.manifest import (
    build_manifest,
    is_excluded,
    read_manifest,
    scan,
    write_manifest,
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_symlink(target, link, target_is_directory=False):
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks not available: {exc}")


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub" / "deeper").mkdir(parents=True)
    (root / "empty").mkdir()
    (root / "a.txt").write_bytes(b"alpha")
    (root / "sub" / "b.bin").write_bytes(b"\x00\x01\x02")
    (root / "sub" / "deeper" / "c.txt").write_bytes(b"")
    return root


def test_scan_hashes_all_files_with_posix_paths(tree):
    result = scan(tree)

    assert result.errors == []
    assert result.files == {
        "a.txt": {"hash": sha256(b"alpha"), "size": 5},
        "sub/b.bin": {"hash": sha256(b"\x00\x01\x02"), "size": 3},
        "sub/deeper/c.txt": {"hash": sha256(b""), "size": 0},
    }


def test_scan_ignores_empty_directories(tree):
    assert not any(key.startswith("empty") for key in scan(tree).files)


def test_scan_reads_large_file(tmp_path):
    data = os.urandom(3 * 1024 * 1024 + 7)
    (tmp_path / "big").write_bytes(data)

    assert scan(tmp_path).files["big"] == {"hash": sha256(data), "size": len(data)}


def test_scan_handles_non_ascii_names(tmp_path):
    (tmp_path / "Übung äöß.txt").write_bytes(b"x")

    assert "Übung äöß.txt" in scan(tmp_path).files


@pytest.mark.parametrize(
    ("patterns", "expected"),
    [
        (["*.txt"], {"sub/b.bin"}),
        (["sub/"], {"a.txt"}),
        (["deeper/"], {"a.txt", "sub/b.bin"}),
        (["sub/b.bin"], {"a.txt", "sub/deeper/c.txt"}),
        (["a.txt/"], {"a.txt", "sub/b.bin", "sub/deeper/c.txt"}),
    ],
)
def test_scan_exclude_patterns(tree, patterns, expected):
    assert set(scan(tree, exclude=patterns).files) == expected


def test_is_excluded_directory_pattern_needs_directory():
    assert is_excluded("node_modules", True, ["node_modules/"])
    assert not is_excluded("node_modules", False, ["node_modules/"])


def test_scan_excludes_given_paths(tree):
    result = scan(tree, exclude_paths=[tree / "sub" / "b.bin"])

    assert "sub/b.bin" not in result.files
    assert "a.txt" in result.files


def test_scan_reports_unreadable_files_and_continues(tree, monkeypatch):
    real_hash_file = manifest.hash_file

    def failing_hash_file(path):
        if str(path).endswith("b.bin"):
            raise PermissionError("access denied")
        return real_hash_file(path)

    monkeypatch.setattr(manifest, "hash_file", failing_hash_file)
    result = scan(tree)

    assert set(result.files) == {"a.txt", "sub/deeper/c.txt"}
    assert result.errors == [("sub/b.bin", "access denied")]


def test_scan_reports_progress(tree):
    calls = []
    scan(tree, progress=lambda files, size: calls.append((files, size)))

    assert len(calls) == 3
    assert calls[-1] == (3, 8)


def test_scan_skips_symlinks_by_default(tree):
    make_symlink(tree / "a.txt", tree / "link.txt")
    make_symlink(tree / "sub", tree / "linkdir", target_is_directory=True)

    assert set(scan(tree).files) == {"a.txt", "sub/b.bin", "sub/deeper/c.txt"}


def test_scan_follows_symlinks_when_requested(tree, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.txt").write_bytes(b"o")
    make_symlink(tree / "a.txt", tree / "link.txt")
    make_symlink(outside, tree / "linkdir", target_is_directory=True)

    files = scan(tree, follow_symlinks=True).files

    assert files["link.txt"] == files["a.txt"]
    assert "linkdir/o.txt" in files


def test_scan_survives_symlink_loop(tree):
    make_symlink(tree, tree / "sub" / "loop", target_is_directory=True)

    files = scan(tree, follow_symlinks=True).files

    assert set(files) == {"a.txt", "sub/b.bin", "sub/deeper/c.txt"}


def test_scan_skips_broken_symlink_when_following(tree):
    make_symlink(tree / "missing", tree / "broken")

    assert "broken" not in scan(tree, follow_symlinks=True).files


def test_build_manifest_adds_metadata_and_sorts():
    files = {"b": {"hash": "2", "size": 2}, "a": {"hash": "1", "size": 1}}
    now = datetime(2026, 10, 21, 9, 30, 15, 123456, tzinfo=UTC)

    m = build_manifest(files, now)

    assert m["format_version"] == 1
    assert m["algorithm"] == "sha256"
    assert m["created"] == "2026-10-21T09:30:15Z"
    assert list(m["files"]) == ["a", "b"]


def test_build_manifest_converts_to_utc():
    now = datetime(2026, 10, 21, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    assert build_manifest({}, now)["created"] == "2026-10-21T09:00:00Z"


def test_write_and_read_manifest_roundtrip(tmp_path):
    path = tmp_path / "m.json"
    m = build_manifest({"ä/ö.txt": {"hash": "1", "size": 1}})

    write_manifest(path, m)

    assert read_manifest(path) == m
    raw = path.read_bytes()
    assert "ä/ö.txt".encode() in raw  # UTF-8, not \u escapes
    assert b"\r\n" not in raw


def test_write_manifest_output_is_deterministic(tmp_path):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    m1 = build_manifest({"b": {"hash": "2", "size": 2}, "a": {"hash": "1", "size": 1}}, now)
    m2 = build_manifest({"a": {"hash": "1", "size": 1}, "b": {"hash": "2", "size": 2}}, now)

    write_manifest(tmp_path / "1.json", m1)
    write_manifest(tmp_path / "2.json", m2)

    assert (tmp_path / "1.json").read_bytes() == (tmp_path / "2.json").read_bytes()


def test_write_manifest_refuses_to_overwrite(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("old", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_manifest(path, build_manifest({}))

    assert path.read_text(encoding="utf-8") == "old"


def test_write_manifest_overwrites_with_force(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("old", encoding="utf-8")

    write_manifest(path, build_manifest({}), force=True)

    assert json.loads(path.read_text(encoding="utf-8"))["files"] == {}
