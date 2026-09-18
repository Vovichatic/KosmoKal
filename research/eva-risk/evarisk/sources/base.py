"""Базовый источник: кеш, ETag, заморозка, честные статусы отказа.

Отказ источника НИКОГДА не превращается в «воздействие не выявлено»
(требование постановки и критерия Т6) — он даёт статус DEGRADED/FAILED,
а полученные ранее записи остаются доступны с отметкой возраста.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from ..config import CONFIG
from ..provenance import Record


class Health(str, Enum):
    OK = "ok"
    CACHED = "cached"          # сеть недоступна, отдаём кеш с возрастом
    FROZEN = "frozen"          # намеренно заморожен пользователем
    DISABLED = "disabled"      # намеренно отключён пользователем
    FAILED = "failed"          # нет ни сети, ни кеша — данных НЕТ


@dataclass
class SourceStatus:
    source_id: str
    health: Health
    last_success: datetime | None
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.health in (Health.OK, Health.CACHED)


class Source:
    source_id: str = "abstract"
    title: str = ""
    units: str = ""
    cadence_s: int = 3600
    publication_lag_s: int = 0
    kind: str = "observation"
    homepage: str = ""

    def __init__(self) -> None:
        self.frozen = False
        self.disabled = False
        self._last_success: datetime | None = None
        self._last_detail = ""

    # --- управление для проверки поведения системы (требование постановки)
    def freeze(self) -> None:
        self.frozen = True

    def unfreeze(self) -> None:
        self.frozen = False

    def disable(self) -> None:
        self.disabled = True

    def enable(self) -> None:
        self.disabled = False

    def status(self, health: Health | None = None) -> SourceStatus:
        if self.disabled:
            health = Health.DISABLED
        elif self.frozen and health is None:
            health = Health.FROZEN
        return SourceStatus(self.source_id, health or Health.OK,
                            self._last_success, self._last_detail)

    def fetch(self, as_of: datetime | None = None) -> tuple[list[Record], SourceStatus]:
        raise NotImplementedError


class HttpSource(Source):
    url: str = ""

    def _cache_path(self) -> Path:
        d = CONFIG.cache_dir / self.source_id
        d.mkdir(parents=True, exist_ok=True)
        return d / "latest.json"

    def _read_cache(self) -> tuple[Any, datetime] | None:
        p = self._cache_path()
        if not p.exists():
            return None
        blob = json.loads(p.read_text())
        return blob["payload"], datetime.fromisoformat(blob["fetched_at"])

    def _write_cache(self, payload: Any, fetched_at: datetime) -> None:
        self._cache_path().write_text(json.dumps(
            {"payload": payload, "fetched_at": fetched_at.isoformat()}, default=str))

    def _http_get(self, url: str) -> Any:
        import requests  # импорт внутри: офлайн-демо работает без него
        headers = {"User-Agent": CONFIG.user_agent}
        last = None
        for attempt in range(3):
            try:
                r = requests.get(url, headers=headers, timeout=CONFIG.http_timeout)
                if r.status_code == 429:
                    time.sleep(2 ** attempt)
                    last = "квота источника исчерпана (429)"
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(last or "запрос не удался")

    def parse(self, payload: Any, fetched_at: datetime) -> list[Record]:
        raise NotImplementedError

    def fetch(self, as_of: datetime | None = None) -> tuple[list[Record], SourceStatus]:
        if self.disabled:
            return [], self.status(Health.DISABLED)
        cached = self._read_cache()
        if self.frozen:
            if cached is None:
                return [], self.status(Health.FAILED)
            payload, fetched_at = cached
            return self.parse(payload, fetched_at), self.status(Health.FROZEN)
        now = datetime.now(timezone.utc)
        try:
            payload = self._http_get(self.url)
            self._write_cache(payload, now)
            self._last_success = now
            self._last_detail = ""
            return self.parse(payload, now), self.status(Health.OK)
        except Exception as exc:  # noqa: BLE001
            self._last_detail = str(exc)
            if cached is None:
                return [], self.status(Health.FAILED)
            payload, fetched_at = cached
            return self.parse(payload, fetched_at), self.status(Health.CACHED)
