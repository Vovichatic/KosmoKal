"""Настройки. Всё из окружения — в коде ни ключей, ни путей."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    cache_dir: Path
    http_timeout: float
    user_agent: str
    spacetrack_user: str | None
    spacetrack_pass: str | None

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            cache_dir=Path(os.getenv("EVARISK_CACHE_DIR", "./.cache")).expanduser(),
            http_timeout=float(os.getenv("EVARISK_HTTP_TIMEOUT", "15")),
            user_agent=os.getenv("EVARISK_USER_AGENT", "eva-risk-prototype/0.1"),
            spacetrack_user=os.getenv("SPACETRACK_USER") or None,
            spacetrack_pass=os.getenv("SPACETRACK_PASS") or None,
        )


CONFIG = Config.from_env()
