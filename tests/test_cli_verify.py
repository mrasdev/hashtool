import json

import pytest

from hashtool import manifest
from hashtool.cli import main
from hashtool.manifest import DEFAULT_MANIFEST_NAME


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "sub" / "b.txt").write_bytes(b"beta")
    return root


@pytest.fixture
def scanned(tree, capsys):
    assert main(["scan", str(tree)]) == 0
    capsys.readouterr()
    return tree


def test_verify_unchanged_exits_zero(scanned, capsys):
    assert main(["verify", str(scanned)]) == 0

    out = capsys.readouterr().out
    assert out == "2 ok, 0 changed, 0 missing, 0 new\n"


def test_verify_reports_differences_sorted_and_padded(scanned, capsys):
    (scanned / "a.txt").write_bytes(b"ALPHA")
    (scanned / "sub" / "b.txt").unlink()
    (scanned / "c.txt").write_bytes(b"new")

    assert main(["verify", str(scanned)]) == 1

    assert capsys.readouterr().out.splitlines() == [
        "CHANGED  a.txt",
        "NEW      c.txt",
        "MISSING  sub/b.txt",
        "0 ok, 1 changed, 1 missing, 1 new",
    ]


def test_verify_never_reports_manifest_as_new(scanned, capsys):
    main(["verify", str(scanned)])

    assert DEFAULT_MANIFEST_NAME not in capsys.readouterr().out


def test_verify_with_manifest_outside_directory(tree, tmp_path, capsys):
    out_file = tmp_path / "elsewhere.json"
    main(["scan", str(tree), "-o", str(out_file)])
    capsys.readouterr()

    assert main(["verify", str(tree), "-m", str(out_file)]) == 0


def test_verify_uses_excludes_stored_by_scan(tree, capsys):
    main(["scan", str(tree), "-e", "*.log"])
    (tree / "debug.log").write_bytes(b"noise")
    capsys.readouterr()

    assert main(["verify", str(tree)]) == 0


def test_verify_missing_manifest_exits_two(tree, capsys):
    assert main(["verify", str(tree)]) == 2
    assert "not found" in capsys.readouterr().err


def test_verify_invalid_manifest_exits_two(tree, capsys):
    (tree / DEFAULT_MANIFEST_NAME).write_text('{"format_version": 9}', encoding="utf-8")

    assert main(["verify", str(tree)]) == 2
    assert "format_version 9" in capsys.readouterr().err


def test_verify_missing_directory_exits_two(tmp_path, capsys):
    assert main(["verify", str(tmp_path / "nope")]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_verify_unreadable_file_exits_two(scanned, capsys, monkeypatch):
    real_hash_file = manifest.hash_file

    def failing(path):
        if str(path).endswith("a.txt"):
            raise PermissionError("access denied")
        return real_hash_file(path)

    monkeypatch.setattr(manifest, "hash_file", failing)

    assert main(["verify", str(scanned)]) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "ERROR    a.txt: access denied"
    assert lines[-1] == "1 ok, 0 changed, 0 missing, 0 new, 1 errors"


def test_verify_differences_and_errors_exit_two(scanned, monkeypatch):
    (scanned / "c.txt").write_bytes(b"new")
    real_hash_file = manifest.hash_file

    def failing(path):
        if str(path).endswith("a.txt"):
            raise PermissionError("access denied")
        return real_hash_file(path)

    monkeypatch.setattr(manifest, "hash_file", failing)

    assert main(["verify", str(scanned)]) == 2


def test_scan_stores_scan_options(tree):
    main(["scan", str(tree), "-e", "b/", "-e", "*.tmp", "--follow-symlinks"])

    data = json.loads((tree / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert data["scan_options"] == {"exclude": ["b/", "*.tmp"], "follow_symlinks": True}
    assert data["format_version"] == 1
