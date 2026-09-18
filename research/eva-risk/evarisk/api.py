"""HTTP-интерфейс. Получение данных, расчёт и представление разделены."""
from __future__ import annotations

from datetime import datetime, timezone

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field
except ImportError:  # интерфейс опционален, ядро работает без него
    FastAPI = None  # type: ignore

from .orbit import demo_tle
from .provenance import Store
from .report import export
from .sources import REGISTRY
from .windows import candidate_starts, completeness, recommend, score_window

if FastAPI is not None:

    class PlanRequest(BaseModel):
        start: datetime
        duration_h: float = Field(6.5, ge=1.0, le=8.0)
        search_h: float = Field(12.0, ge=0.0, le=24.0)
        step_min: int = Field(30, ge=5, le=240)

    app = FastAPI(title="ВКД-Риск", version="0.1.0")

    @app.get("/sources")
    def sources() -> dict:
        return {sid: {"title": s.title, "units": s.units,
                      "cadence_s": s.cadence_s,
                      "publication_lag_s": s.publication_lag_s,
                      "kind": s.kind, "homepage": s.homepage,
                      "frozen": s.frozen, "disabled": s.disabled}
                for sid, s in REGISTRY.items()}

    @app.post("/sources/{source_id}/{action}")
    def control(source_id: str, action: str) -> dict:
        """Заморозка и отключение источника — проверка поведения системы."""
        src = REGISTRY.get(source_id)
        if src is None or action not in ("freeze", "unfreeze", "disable", "enable"):
            raise HTTPException(404, "нет такого источника или действия")
        getattr(src, action)()
        return {"source_id": source_id, "frozen": src.frozen, "disabled": src.disabled}

    @app.post("/plan")
    def plan(req: PlanRequest) -> dict:
        store = Store()
        protons, kps, scales = [], [], {"S": None, "G": None, "R": None}
        tle = demo_tle()
        statuses, status_text = {}, {}
        for sid, src in REGISTRY.items():
            recs, st = src.fetch()
            statuses[sid] = st.usable
            status_text[sid] = st.health.value
            for r in recs:
                store.put(r)
            if sid == "swpc.goes.protons":
                protons = recs
            elif sid == "swpc.kp":
                kps = recs
            elif sid == "swpc.alerts" and recs:
                scales = recs[0].payload["scales"]
            elif sid == "celestrak.gp.iss" and recs and "TLE_LINE1" in recs[0].payload:
                tle = (recs[0].payload["TLE_LINE1"], recs[0].payload["TLE_LINE2"])

        limits = {"swpc.goes.protons": 1800, "swpc.kp": 1800,
                  "celestrak.gp.iss": 3 * 3600, "swpc.alerts": 3 * 3600}
        comp = completeness(statuses, store.max_age(), limits)
        start = req.start.astimezone(timezone.utc)
        scores = [score_window(t0, req.duration_h, tle, protons, kps, scales,
                               [], comp, store, step_s=300)
                  for t0 in candidate_starts(start, req.search_h, req.step_min)]
        verdict = recommend(scores)
        return export(req.model_dump(mode="json"), scores, verdict, store,
                      None, status_text)

    @app.get("/evidence/{node_hash}")
    def evidence(node_hash: str) -> dict:
        raise HTTPException(501, "граф доказательств хранится по запросу расчёта")
