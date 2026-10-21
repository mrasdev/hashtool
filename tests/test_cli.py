import io
import json

import pytest

from hashtool.cli import Progress, format_size, main
from hashtool.manifest import DEFAULT_MANIFEST_NAME


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "data"
    (root / "sub").mkdir(parents=True)
    (root / "a.txt").write_bytes(b"alpha")
    (root / "sub" / "b.txt").write_bytes(b"beta")
    return root


def test_no_command_is_usage_error(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])

    assert exc.value.code == 2
    assert "usage" in capsys.readouterr().err


def test_scan_writes_default_manifest(tree, capsys):
    assert main(["scan", str(tree)]) == 0

    manifest = json.loads((tree / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"a.txt", "sub/b.txt"}
    assert "2 files" in capsys.readouterr().out


def test_scan_writes_to_output_option(tree, tmp_path):
    out = tmp_path / "custom.json"

    assert main(["scan", str(tree), "-o", str(out)]) == 0
    assert out.exists()
    assert not (tree / DEFAULT_MANIFEST_NAME).exists()


def test_scan_refuses_existing_manifest(tree, capsys):
    main(["scan", str(tree)])
    capsys.readouterr()

    assert main(["scan", str(tree)]) == 1
    assert "--force" in capsys.readouterr().err


def test_rescan_with_force_excludes_manifest_itself(tree):
    main(["scan", str(tree)])

    assert main(["scan", str(tree), "--force"]) == 0

    manifest = json.loads((tree / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert DEFAULT_MANIFEST_NAME not in manifest["files"]


def test_scan_exclude_option(tree):
    main(["scan", str(tree), "-e", "sub/", "--exclude", "*.log"])

    manifest = json.loads((tree / DEFAULT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert set(manifest["files"]) == {"a.txt"}


def test_scan_rejects_missing_directory(tmp_path, capsys):
    assert main(["scan", str(tmp_path / "nope")]) == 1
    assert "not a directory" in capsys.readouterr().err


def test_scan_without_tty_prints_no_progress(tree, capsys):
    main(["scan", str(tree)])

    assert "Scanning" not in capsys.readouterr().err


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def test_progress_writes_on_tty_and_clears_line():
    stream = FakeTTY()
    progress = Progress(stream, interval=0)

    progress(3, 2048)
    progress.finish()

    assert "Scanning: 3 files, 2.0 KiB" in stream.getvalue()
    assert stream.getvalue().endswith("\r\033[K")


def test_progress_silent_without_tty():
    stream = io.StringIO()
    progress = Progress(stream, interval=0)

    progress(1, 1)
    progress.finish()

    assert stream.getvalue() == ""


@pytest.mark.parametrize(
    ("size", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (5 * 1024**2, "5.0 MiB")],
)
def test_format_size(size, expected):
    assert format_size(size) == expected
