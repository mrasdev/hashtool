import json

import pytest

from hashtool import manifest
from hashtool.manifest import (
    ManifestError,
    Status,
    build_manifest,
    compare,
    get_scan_options,
    load_manifest,
    scan,
    verify,
    write_manifest,
)


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "sub" / "b.txt").write_bytes(b"beta")
    return root


def entries(result):
    return [(e.status, e.path) for e in result.entries]


# --- compare: pure classification ----------------------------------------


def test_compare_classifies_all_statuses():
    stored = {
        "same": {"hash": "h1", "size": 1},
        "changed_hash": {"hash": "h2", "size": 2},
        "changed_size": {"hash": "h3", "size": 3},
        "missing": {"hash": "h4", "size": 4},
    }
    current = {"same": 1, "changed_hash": 2, "changed_size": 99, "new": 5}
    hashes = {"same": "h1", "changed_hash": "other"}

    result = compare(stored, current, hashes.__getitem__)

    assert entries(result) == [
        (Status.CHANGED, "changed_hash"),
        (Status.CHANGED, "changed_size"),
        (Status.MISSING, "missing"),
        (Status.NEW, "new"),
    ]
    assert result.counts[Status.OK] == 1


def test_compare_does_not_hash_when_size_differs():
    hashed = []

    def get_hash(rel):
        hashed.append(rel)
        return "x"

    compare({"f": {"hash": "x", "size": 1}}, {"f": 2}, get_hash)

    assert hashed == []


def test_compare_does_not_hash_new_files():
    hashed = []
    compare({}, {"new": 1}, lambda rel: hashed.append(rel) or "x")

    assert hashed == []


def test_compare_reports_hash_errors():
    def get_hash(rel):
        raise PermissionError("access denied")

    result = compare({"f": {"hash": "x", "size": 1}}, {"f": 1}, get_hash)

    assert [(e.status, e.path, e.message) for e in result.entries] == [
        (Status.ERROR, "f", "access denied")
    ]
    assert result.has_errors


def test_compare_output_sorted_by_path():
    stored = {"b": {"hash": "x", "size": 1}, "d": {"hash": "x", "size": 1}}
    current = {"c": 1, "a": 1}

    result = compare(stored, current, lambda rel: "x")

    assert [e.path for e in result.entries] == ["a", "b", "c", "d"]


# --- verify: against the file system --------------------------------------


def manifest_for(root, **options):
    files = scan(root, **options).files
    return build_manifest(files, scan_options={"exclude": [], "follow_symlinks": False, **options})


def test_verify_unchanged_directory(tree):
    result = verify(tree, manifest_for(tree))

    assert result.entries == []
    assert result.counts[Status.OK] == 2
    assert not result.has_differences


def test_verify_detects_same_size_content_change(tree):
    m = manifest_for(tree)
    (tree / "a.txt").write_bytes(b"ALPHA")

    assert entries(verify(tree, m)) == [(Status.CHANGED, "a.txt")]


def test_verify_detects_size_change_without_hashing(tree, monkeypatch):
    m = manifest_for(tree)
    (tree / "a.txt").write_bytes(b"alphabet")
    hashed = []
    real_hash_file = manifest.hash_file
    monkeypatch.setattr(manifest, "hash_file", lambda p: hashed.append(str(p)) or real_hash_file(p))

    assert entries(verify(tree, m)) == [(Status.CHANGED, "a.txt")]
    assert not any(p.endswith("a.txt") for p in hashed)


def test_verify_detects_missing_and_new(tree):
    m = manifest_for(tree)
    (tree / "a.txt").unlink()
    (tree / "sub" / "c.txt").write_bytes(b"new")

    result = verify(tree, m)

    assert entries(result) == [(Status.MISSING, "a.txt"), (Status.NEW, "sub/c.txt")]
    assert result.has_differences


def test_verify_applies_stored_excludes(tree):
    (tree / ".git").mkdir()
    (tree / ".git" / "HEAD").write_bytes(b"ref")
    m = manifest_for(tree, exclude=[".git/"])
    (tree / ".git" / "index").write_bytes(b"new git file")

    assert verify(tree, m).entries == []


def test_verify_accepts_manifest_without_scan_options(tree):
    m = build_manifest(scan(tree).files)
    assert "scan_options" not in m

    assert verify(tree, m).entries == []


def test_verify_excludes_given_paths(tree):
    m = manifest_for(tree)
    (tree / "hashtool-manifest.json").write_text("{}", encoding="utf-8")

    result = verify(tree, m, exclude_paths=[tree / "hashtool-manifest.json"])

    assert result.entries == []


def test_verify_reports_unreadable_file(tree, monkeypatch):
    m = manifest_for(tree)
    real_hash_file = manifest.hash_file

    def failing(path):
        if str(path).endswith("a.txt"):
            raise PermissionError("access denied")
        return real_hash_file(path)

    monkeypatch.setattr(manifest, "hash_file", failing)
    result = verify(tree, m)

    assert entries(result) == [(Status.ERROR, "a.txt")]
    assert result.has_errors


def test_verify_reports_progress(tree):
    calls = []
    verify(tree, manifest_for(tree), progress=lambda n, size: calls.append((n, size)))

    assert calls[-1] == (2, 9)


# --- manifest loading and validation --------------------------------------


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_manifest_roundtrip(tmp_path):
    m = build_manifest({"a": {"hash": "x", "size": 1}}, scan_options={"exclude": ["*.tmp"]})
    write_manifest(tmp_path / "m.json", m)

    assert load_manifest(tmp_path / "m.json") == m


def test_load_manifest_missing_file(tmp_path):
    with pytest.raises(ManifestError, match="not found"):
        load_manifest(tmp_path / "nope.json")


def test_load_manifest_invalid_json(tmp_path):
    path = tmp_path / "m.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ManifestError, match="not valid JSON"):
        load_manifest(path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"format_version": 2}, "format_version 2"),
        ({"algorithm": "md5"}, "algorithm 'md5'"),
        ({"files": None}, "files"),
        ({"files": {"a": {"hash": 1, "size": 1}}}, "entry 'a'"),
        ({"files": {"a": {"hash": "x"}}}, "entry 'a'"),
        ({"scan_options": {"exclude": "*.tmp"}}, "scan_options"),
        ({"scan_options": {"follow_symlinks": "yes"}}, "scan_options"),
    ],
)
def test_load_manifest_rejects_invalid_content(tmp_path, change, message):
    data = {**build_manifest({"a": {"hash": "x", "size": 1}}), **change}
    path = write_json(tmp_path / "m.json", data)

    with pytest.raises(ManifestError, match=message):
        load_manifest(path)


def test_load_manifest_rejects_non_object(tmp_path):
    path = write_json(tmp_path / "m.json", [1, 2])

    with pytest.raises(ManifestError):
        load_manifest(path)


def test_get_scan_options_defaults():
    assert get_scan_options({}) == ([], False)
    assert get_scan_options({"scan_options": {"exclude": ["a/"]}}) == (["a/"], False)
