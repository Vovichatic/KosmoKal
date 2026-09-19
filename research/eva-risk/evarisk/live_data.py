"""Continuously refreshed, cadence-aware snapshot of all live sources."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from threading import RLock
from typing import Any

from .provenance import Record, Store
from .sources import REGISTRY
from .sources.base import SourceStatus


@dataclass(frozen=True)
class LiveBatch:
    generated_at: datetime
    records: dict[str, tuple[Record, ...]]
    statuses: dict[str, SourceStatus]

    def store(self) -> Store:
        store = Store()
        for records in self.records.values():
            for record in records:
                store.put(record)
        return store

    def payload(self, include_records: bool = True) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        sources: dict[str, Any] = {}
        for source_id, source in REGISTRY.items():
            records = self.records.get(source_id, ())
            status = self.statuses.get(source_id)
            latest = max(
                (record.observed_at or record.issued_at for record in records
                 if record.observed_at or record.issued_at),
                default=None,
            )
            item = {
                "title": source.title,
                "health": status.health.value if status else "pending",
                "usable": status.usable if status else False,
                "detail": status.detail if status else "initial refresh pending",
                "record_count": len(records),
                "cadence_s": source.cadence_s,
                "publication_lag_s": source.publication_lag_s,
                "latest_observation": latest.isoformat() if latest else None,
                "age_s": round((now - latest).total_seconds(), 1) if latest else None,
            }
            if include_records:
                item["records"] = [record.to_dict() for record in records]
            sources[source_id] = item
        store = self.store()
        return {
            "schema_version": 1,
            "generated_at": self.generated_at.isoformat(),
            "provenance_root": store.root(),
            "provenance_nodes": len(store),
            "sources": sources,
        }


class LiveDataService:
    def __init__(self) -> None:
        self._lock = RLock()
        self._records: dict[str, tuple[Record, ...]] = {}
        self._statuses: dict[str, SourceStatus] = {}
        self._last_attempt: dict[str, datetime] = {}
        self._generated_at: datetime | None = None

    def refresh(self, force: bool = False) -> LiveBatch:
        now = datetime.now(timezone.utc)
        with self._lock:
            due = {
                source_id: source
                for source_id, source in REGISTRY.items()
                if force
                or source_id not in self._records
                or (now - self._last_attempt.get(source_id, datetime.min.replace(tzinfo=timezone.utc))).total_seconds()
                >= max(60, source.cadence_s)
            }
            for source_id in due:
                self._last_attempt[source_id] = now

        if due:
            with ThreadPoolExecutor(max_workers=len(due)) as pool:
                futures = {source_id: pool.submit(source.fetch) for source_id, source in due.items()}
                updates = {source_id: future.result() for source_id, future in futures.items()}
            with self._lock:
                for source_id, (records, status) in updates.items():
                    self._records[source_id] = tuple(records)
                    self._statuses[source_id] = status
                self._generated_at = datetime.now(timezone.utc)
        return self.get(refresh_if_empty=False)

    def get(self, refresh_if_empty: bool = True) -> LiveBatch:
        with self._lock:
            empty = not self._records
        if empty and refresh_if_empty:
            return self.refresh(force=True)
        with self._lock:
            return LiveBatch(
                generated_at=self._generated_at or datetime.now(timezone.utc),
                records=dict(self._records),
                statuses=dict(self._statuses),
            )

    def invalidate(self, source_id: str) -> None:
        with self._lock:
            self._last_attempt.pop(source_id, None)


@lru_cache(maxsize=1)
def live_data_service() -> LiveDataService:
    return LiveDataService()
