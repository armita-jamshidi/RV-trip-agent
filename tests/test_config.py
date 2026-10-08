import pytest

from dave.config import MissingKeyError, load_settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("ANTHROPIC_API_KEY", "EIA_API_KEY", "DAVE_CACHE_DIR", "DAVE_OFFLINE"):
        monkeypatch.delenv(name, raising=False)


def test_reads_keys_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EIA_API_KEY=abc123\nDAVE_OFFLINE=1\n")
    settings = load_settings(env)
    assert settings.require("EIA_API_KEY") == "abc123"
    assert settings.offline is True
    monkeypatch.delenv("EIA_API_KEY")  # load_dotenv writes to os.environ
    monkeypatch.delenv("DAVE_OFFLINE")


def test_environment_wins_over_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("EIA_API_KEY=from-file\n")
    monkeypatch.setenv("EIA_API_KEY", "from-env")
    assert load_settings(env).require("EIA_API_KEY") == "from-env"


def test_missing_key_explains_how_to_fix(tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    with pytest.raises(MissingKeyError, match=r"ANTHROPIC_API_KEY.*\.env\.example"):
        settings.require("ANTHROPIC_API_KEY")


def test_defaults(tmp_path):
    settings = load_settings(tmp_path / "missing.env")
    assert str(settings.cache_dir) == ".cache/dave"
    assert settings.offline is False
