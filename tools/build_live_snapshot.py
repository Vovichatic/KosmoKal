#!/usr/bin/env python3
"""Fetch all public live sources and write one atomic JSON snapshot."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research" / "eva-risk"))

from evarisk.live_data import live_data_service  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "live" / "latest.json")
    args = parser.parse_args()
    payload = live_data_service().refresh(force=True).payload(include_records=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, args.output)
    print(json.dumps({
        "output": str(args.output),
        "generated_at": payload["generated_at"],
        "provenance_root": payload["provenance_root"],
        "sources": {key: value["record_count"] for key, value in payload["sources"].items()},
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

