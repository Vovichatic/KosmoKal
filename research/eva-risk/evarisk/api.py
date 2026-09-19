"""HTTP-интерфейс. Получение данных, расчёт и представление разделены."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ImportError:  # интерфейс опционален, ядро работает без него
    FastAPI = None  # type: ignore

from .orbit import demo_tle
from .ml import live_radiation_forecaster, radiation_forecaster
from .provenance import Store
from .report import export
from .sources import REGISTRY
from .windows import candidate_starts, completeness, recommend, score_window
from .cli import synthetic_event

if FastAPI is not None:

    class PlanRequest(BaseModel):
        start: datetime
        duration_h: float = Field(6.5, ge=1.0, le=8.0)
        search_h: float = Field(12.0, ge=0.0, le=24.0)
        step_min: int = Field(30, ge=5, le=240)
        mode: str = Field("current", pattern="^(current|historical)$")

    app = FastAPI(title="ВКД-Риск", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "ml": {
            "historical": radiation_forecaster().status(),
            "live": live_radiation_forecaster().status(),
        }}

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
        start = req.start.astimezone(timezone.utc)
        if req.mode == "historical":
            forecast = radiation_forecaster().predict(start)
            peak_pfu = 900.0 if forecast and forecast.probability >= forecast.as_dict()["threshold"] else 30.0
            protons, kps = synthetic_event(start - timedelta(hours=6), peak_pfu=peak_pfu)
            for record in protons + kps:
                store.put(record)
            statuses = {sid: True for sid in REGISTRY}
            status_text = {sid: "historical-replay" for sid in REGISTRY}
            ages = {sid: 300.0 for sid in REGISTRY}
            scales = {"S": 3, "G": 4, "R": 2} if peak_pfu > 100 else scales
        else:
            with ThreadPoolExecutor(max_workers=len(REGISTRY)) as pool:
                fetched = {sid: pool.submit(src.fetch) for sid, src in REGISTRY.items()}
            for sid, future in fetched.items():
                recs, st = future.result()
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
            ages = store.max_age()

        limits = {"swpc.goes.protons": 1800, "swpc.kp": 1800,
                  "celestrak.gp.iss": 3 * 3600, "swpc.alerts": 3 * 3600}
        comp = completeness(statuses, ages, limits)
        scores = [score_window(t0, req.duration_h, tle, protons, kps, scales,
                               [], comp, store, step_s=300)
                  for t0 in candidate_starts(start, req.search_h, req.step_min)]
        verdict = recommend(scores)
        payload = export(req.model_dump(mode="json"), scores, verdict, store,
                         start if req.mode == "historical" else None, status_text)
        historical_ml = radiation_forecaster()
        live_ml = live_radiation_forecaster()
        moments = [datetime.fromisoformat(window["start"]) for window in payload["windows"]]
        if req.mode == "historical":
            for window, moment in zip(payload["windows"], moments):
                prediction = historical_ml.predict(moment)
                window["ml_forecast"] = prediction.as_dict() if prediction else None
        else:
            predictions = live_ml.predict_many(moments, protons, kps, tle)
            for window, prediction in zip(payload["windows"], predictions):
                window["ml_forecast"] = prediction
        payload["ml"] = historical_ml.status() if req.mode == "historical" else live_ml.status()
        payload["ai_summary"] = _ai_summary(payload)
        return payload

    def _ai_summary(payload: dict) -> dict:
        candidates = [window for window in payload["windows"] if window["on_pareto_front"]]
        with_ml = [window for window in candidates if window.get("ml_forecast")]
        if not with_ml:
            return {
                "status": "physics-only",
                "title": "ML-прогноз не применён",
                "text": "CatBoost валидирован на историческом holdout мая–июня 2024; для live-окна показан физический контур.",
                "recommended_start": None,
            }
        choice = min(with_ml, key=lambda item: (
            item["ml_forecast"]["probability"], item["dose_usv_proxy"], -item["completeness"]
        ))
        probability = choice["ml_forecast"]["probability"]
        is_live = choice["ml_forecast"]["scope"].startswith("live")
        detail = (
            f"Live-модель использует GOES, Kp и положение МКС; уверенность проекции: "
            f"{choice['ml_forecast']['confidence']}."
            if is_live else "Выбор сделан только среди окон Парето-фронта."
        )
        return {
            "status": "ml-assisted",
            "title": "AI-ассистент выбрал окно с минимальным ML-риском",
            "text": f"Вероятность превышения локального Q99 в следующие 6 часов: {probability:.0%}. {detail}",
            "recommended_start": choice["start"],
        }

    @app.get("/evidence/{node_hash}")
    def evidence(node_hash: str) -> dict:
        raise HTTPException(501, "граф доказательств хранится по запросу расчёта")
