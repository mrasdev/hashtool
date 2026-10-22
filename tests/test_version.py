from importlib.metadata import version

import pytest

import hashtool
from hashtool.cli import main


def test_version_option_prints_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])

    assert exc.value.code == 0
    assert capsys.readouterr().out == f"hashtool {version('hashtool')}\n"


def test_package_exposes_version():
    assert hashtool.__version__ == version("hashtool")
