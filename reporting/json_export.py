"""Full JSON evidence package (includes raw exported CSV + SHA-256 per visual)."""
from __future__ import annotations

import json

from core.contracts import ComparisonRunResult


def build_json(run: ComparisonRunResult, include_raw: bool = True) -> str:
    data = run.model_dump(mode="json")
    if not include_raw:
        for side in ("original", "migrated"):
            for v in data[side]["visuals"]:
                v["raw_csv"] = None
    data["_meta"] = {
        "data_source": "MOCK_FIXTURE" if run.is_mock else "LIVE_POWER_BI",
        "integrity": "raw_csv SHA-256 recorded per visual in raw_sha256",
        "schema": "ComparisonRunResult (core/contracts.py)",
    }
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
