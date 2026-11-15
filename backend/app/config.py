from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(__file__).resolve().parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MARSX_", extra="ignore")

    database_url: str = f"sqlite:///{(BACKEND_DIR / 'marsx.db').as_posix()}"
    cache_dir: Path = BACKEND_DIR / "data_cache"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    # AI: when no Anthropic credential is configured MARS AI runs its deterministic tool planner.
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_max_tool_rounds: int = 8
    # network
    http_timeout_s: float = 60.0
    offline: bool = False            # true => never touch the network, cache/snapshots only
    weather_ttl_s: int = 6 * 3600


settings = Settings()
settings.cache_dir.mkdir(parents=True, exist_ok=True)
