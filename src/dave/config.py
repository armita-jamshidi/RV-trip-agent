"""Settings and secrets. Keys come from the environment or a local .env file, never from git."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

API_KEYS = ("ANTHROPIC_API_KEY", "FOURSQUARE_API_KEY", "RIDB_API_KEY", "EIA_API_KEY")


class MissingKeyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    cache_dir: Path
    offline: bool
    keys: dict[str, str]

    def require(self, name: str) -> str:
        """Return an API key, or explain exactly how to provide it."""
        value = self.keys.get(name)
        if not value:
            raise MissingKeyError(
                f"{name} is not set. Add it to your environment or to .env (see .env.example)."
            )
        return value


def load_settings(env_file: Path | str = ".env") -> Settings:
    load_dotenv(env_file, override=False)
    return Settings(
        cache_dir=Path(os.environ.get("DAVE_CACHE_DIR", ".cache/dave")),
        offline=os.environ.get("DAVE_OFFLINE", "") in {"1", "true", "yes"},
        keys={name: os.environ[name] for name in API_KEYS if os.environ.get(name)},
    )
