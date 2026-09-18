"""Контентно-адресуемый граф происхождения.

Один и тот же граф решает три задачи:
  1. прослеживаемость предупреждения до исходной записи (критерий О4);
  2. отсечение по времени публикации для строгого replay (критерий Т4);
  3. дельта-синхронизация Земля-Космос: имя узла = хеш содержимого.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Iterable

OBSERVATION = "observation"
EXTERNAL_FORECAST = "external_forecast"
TEAM_COMPUTATION = "team_computation"
KINDS = (OBSERVATION, EXTERNAL_FORECAST, TEAM_COMPUTATION)


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


def content_hash(payload: Any, meta: dict) -> str:
    h = hashlib.blake2b(digest_size=16)
    h.update(_canonical(meta))
    h.update(b"\x00")
    h.update(_canonical(payload))
    return h.hexdigest()


@dataclass
class Record:
    """Узел графа. Неизменяемый: любое изменение даёт новый хеш."""

    source_id: str
    kind: str
    payload: Any
    units: str = ""
    url: str | None = None
    issued_at: datetime | None = None      # когда ИСТОЧНИК опубликовал
    observed_at: datetime | None = None    # к какому моменту относится величина
    fetched_at: datetime | None = None     # когда МЫ получили
    parents: tuple[str, ...] = ()
    note: str = ""
    hash: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"неизвестный kind: {self.kind}")
        meta = {
            "source_id": self.source_id,
            "kind": self.kind,
            "units": self.units,
            "url": self.url,
            "issued_at": self.issued_at,
            "observed_at": self.observed_at,
            "parents": list(self.parents),
        }
        object.__setattr__(self, "hash", content_hash(self.payload, meta))

    def age_seconds(self, now: datetime) -> float | None:
        """Age of Information: возраст самой свежей величины в узле."""
        ref = self.observed_at or self.issued_at
        return None if ref is None else (now - ref).total_seconds()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["hash"] = self.hash
        d["parents"] = list(self.parents)
        return d


class Store:
    """Хранилище узлов + меркл-корень для дельта-обмена."""

    def __init__(self) -> None:
        self._nodes: dict[str, Record] = {}

    def put(self, rec: Record) -> str:
        self._nodes[rec.hash] = rec
        return rec.hash

    def get(self, h: str) -> Record:
        return self._nodes[h]

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, h: object) -> bool:
        return h in self._nodes

    def manifest(self) -> list[str]:
        return sorted(self._nodes)

    def root(self) -> str:
        """Меркл-корень. Обмен 32 байтами вместо всего среза данных."""
        h = hashlib.blake2b(digest_size=16)
        for k in self.manifest():
            h.update(bytes.fromhex(k))
        return h.hexdigest()

    def missing_from(self, remote_manifest: Iterable[str]) -> list[str]:
        """Что у нас есть, а у той стороны нет — только это и передаём."""
        remote = set(remote_manifest)
        return [h for h in self.manifest() if h not in remote]

    def lineage(self, h: str) -> list[Record]:
        """Обход вверх до листьев-источников: клик «почему» в интерфейсе."""
        seen, order, stack = set(), [], [h]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self._nodes:
                continue
            seen.add(cur)
            rec = self._nodes[cur]
            order.append(rec)
            stack.extend(rec.parents)
        return order

    def as_of(self, cutoff: datetime) -> "Store":
        """Строгий replay: всё, опубликованное позже отсечки, не существует."""
        out = Store()
        for rec in self._nodes.values():
            stamp = rec.issued_at or rec.observed_at or rec.fetched_at
            if stamp is None or stamp <= cutoff:
                out.put(rec)
        return out

    def by_source(self, source_id: str) -> list[Record]:
        return [r for r in self._nodes.values() if r.source_id == source_id]

    def max_age(self, now: datetime | None = None) -> dict[str, float]:
        now = now or datetime.now(timezone.utc)
        ages: dict[str, float] = {}
        for rec in self._nodes.values():
            a = rec.age_seconds(now)
            if a is None:
                continue
            ages[rec.source_id] = min(ages.get(rec.source_id, a), a)
        return ages
