from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///./data/bot.db"


@dataclass(frozen=True, slots=True)
class Config:
    token: str
    database_url: str
    log_level: str
    health_host: str
    health_port: int


def _ensure_sqlite_dir(url: str) -> None:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite" and parsed.database not in (None, "", ":memory:"):
        Path(parsed.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "YOUR_TOKEN":
        raise RuntimeError("DISCORD_TOKEN is not set. Copy .env to .env and fill it in.")
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL).strip()
    _ensure_sqlite_dir(database_url)
    return Config(token=token, database_url=database_url, log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        health_host=os.getenv("HEALTH_HOST", "127.0.0.1"),
        health_port=int(os.getenv("HEALTH_PORT", "8080")),
    )
