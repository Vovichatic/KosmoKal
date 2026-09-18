"""Выгрузка: читаемый отчёт + машиночитаемый JSON с полной трассировкой."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import ALGO_VERSION
from .provenance import Store
from .windows import WindowScore


def export(request: dict, scores: list[WindowScore], verdict: dict,
           store: Store, cutoff: datetime | None,
           source_status: dict[str, str]) -> dict[str, Any]:
    return {
        "algo_version": ALGO_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request": request,
        "replay_cutoff": cutoff.isoformat() if cutoff else None,
        "source_status": source_status,
        "provenance_root": store.root(),
        "provenance_nodes": len(store),
        "verdict": verdict["verdict"],
        "reason": verdict["reason"],
        "windows": [
            {
                "start": s.start.isoformat(),
                "duration_h": s.duration_h,
                "dose_usv_proxy": round(s.dose_usv, 1),
                "p_penetration": s.p_penetration,
                "conjunction_overlap_min": s.conjunction_overlap_min,
                "completeness": s.completeness,
                "weather_combined": round(s.weather_combined, 4),
                "kp_max": s.kp_max,
                "saa_minutes": round(s.saa_minutes, 1),
                "on_pareto_front": not s.dominated_by,
                "explanation": s.explanation,
                "evidence_hash": s.record.hash if s.record else None,
            }
            for s in scores
        ],
    }


def to_text(payload: dict[str, Any]) -> str:
    lines = [
        "ВКД-Риск — результат расчёта",
        f"версия алгоритма: {payload['algo_version']}",
        f"корень графа доказательств: {payload['provenance_root']} "
        f"({payload['provenance_nodes']} узлов)",
        f"отсечка replay: {payload['replay_cutoff'] or 'нет (текущий режим)'}",
        "",
        f"ВЕРДИКТ: {payload['verdict']}",
        f"почему: {payload['reason']}",
        "",
        "Окна:",
    ]
    for w in payload["windows"]:
        mark = "★" if w["on_pareto_front"] else " "
        lines.append(
            f" {mark} {w['start'][11:16]} UTC  {w['duration_h']:.1f} ч  "
            f"доза-прокси {w['dose_usv_proxy']:>7.1f} мкЗв  "
            f"P(пробой) {w['p_penetration']:.2e}  "
            f"TCA {w['conjunction_overlap_min']:>4.0f} мин  "
            f"полнота {w['completeness']:.0%}")
    lines += ["", "Статус источников:"]
    for sid, st in payload["source_status"].items():
        lines.append(f"  {sid}: {st}")
    lines += ["", "Доза-прокси — оценка внешней обстановки на траектории, "
                  "а не доза конкретного человека."]
    return "\n".join(lines)


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)
