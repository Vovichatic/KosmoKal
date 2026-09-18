"""Демонстрационный прогон. Работает офлайн на встроенных данных."""
from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone

from .orbit import demo_tle
from .provenance import Record, Store, OBSERVATION
from .report import dumps, export, to_text
from .sources import REGISTRY
from .windows import candidate_starts, completeness, recommend, score_window


def synthetic_event(start: datetime, hours: int = 36, peak_pfu: float = 900.0):
    """Синтетическое SEP-событие для офлайн-демо и модульных тестов."""
    protons, kps = [], []
    for i in range(hours * 12):
        t = start + timedelta(minutes=5 * i)
        h = i / 12.0
        shape = 0.0 if h < 6 else peak_pfu * ((h - 6) / 4) ** 2 / (1 + ((h - 6) / 4) ** 3)
        for label, scale in ((">=10 MeV", 1.0), (">=50 MeV", 0.12), (">=100 MeV", 0.03)):
            protons.append(Record(
                source_id="swpc.goes.protons", kind=OBSERVATION, units="pfu",
                payload={"energy": label, "flux": 0.3 + shape * scale},
                observed_at=t, issued_at=t))
    for i in range(hours * 12):
        t = start + timedelta(minutes=5 * i)
        h = i / 12.0
        kp = 2.0 if h < 8 else min(8.0, 2.0 + (h - 8) * 0.6)
        kps.append(Record(source_id="swpc.kp", kind=OBSERVATION, units="Kp",
                          payload={"kp": kp}, observed_at=t, issued_at=t))
    return protons, kps


def run(args) -> int:
    random.seed(7)
    store = Store()
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    statuses: dict[str, bool] = {}
    status_text: dict[str, str] = {}

    if args.offline:
        protons, kps = synthetic_event(start - timedelta(hours=6),
                                       peak_pfu=args.peak_pfu)
        for r in protons + kps:
            store.put(r)
        tle = demo_tle()
        scales = {"S": 3, "G": 4, "R": 2} if args.peak_pfu > 100 else {"S": None, "G": None, "R": None}
        statuses = {"swpc.goes.protons": True, "swpc.kp": True,
                    "celestrak.gp.iss": True, "swpc.alerts": True}
        status_text = {k: "offline-демо" for k in statuses}
        ages = {k: 300.0 for k in statuses}
    else:
        protons, kps, scales = [], [], {"S": None, "G": None, "R": None}
        tle = demo_tle()
        for sid, src in REGISTRY.items():
            recs, st = src.fetch()
            statuses[sid] = st.usable
            status_text[sid] = st.health.value + (f" — {st.detail}" if st.detail else "")
            for r in recs:
                store.put(r)
            if sid == "swpc.goes.protons":
                protons = recs
            elif sid == "swpc.kp":
                kps = recs
            elif sid == "swpc.alerts" and recs:
                scales = recs[0].payload["scales"]
            elif sid == "celestrak.gp.iss" and recs:
                row = recs[0].payload
                if "TLE_LINE1" in row:
                    tle = (row["TLE_LINE1"], row["TLE_LINE2"])
        ages = store.max_age()

    limits = {"swpc.goes.protons": 1800, "swpc.kp": 1800,
              "celestrak.gp.iss": 3 * 3600, "swpc.alerts": 3 * 3600}
    comp = completeness(statuses, ages, limits)

    conjunctions = [{"object": "COSMOS 1408 DEB", "tca": start + timedelta(hours=5.2),
                     "miss_km": 1.4, "pc": 3e-5}]

    scores = []
    for t0 in candidate_starts(start, args.search_h, args.step_min):
        scores.append(score_window(t0, args.duration_h, tle, protons, kps,
                                   scales, conjunctions, comp, store,
                                   step_s=args.step_s))
    verdict = recommend(scores)
    payload = export(
        {"start": args.start, "duration_h": args.duration_h,
         "search_h": args.search_h, "mode": "offline" if args.offline else "live"},
        scores, verdict, store, None, status_text)

    print(to_text(payload))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(dumps(payload))
        print(f"\nJSON сохранён: {args.json}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="evarisk", description="Планирование окна ВКД")
    p.add_argument("--start", default="2024-05-11T00:00:00")
    p.add_argument("--duration-h", type=float, default=6.5)
    p.add_argument("--search-h", type=float, default=12.0)
    p.add_argument("--step-min", type=int, default=120)
    p.add_argument("--step-s", type=int, default=300)
    p.add_argument("--peak-pfu", type=float, default=900.0)
    p.add_argument("--offline", action="store_true", help="без сети, на синтетике")
    p.add_argument("--json", default="")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
