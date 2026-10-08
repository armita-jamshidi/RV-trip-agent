import pytest

import dave
from dave.cli import main


def test_version():
    assert dave.__version__ == "0.1.0"


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "dave 0.1.0" in capsys.readouterr().out


def test_cli_help(capsys):
    assert main([]) == 0
    assert "Plan an RV road trip" in capsys.readouterr().out
