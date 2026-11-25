"""Visual inventory summaries for UI/reporting (derived from extraction evidence)."""
from __future__ import annotations

from typing import Any

from core.contracts import ReportExtraction


def inventory(ext: ReportExtraction) -> list[dict[str, Any]]:
    pages = {p.name: p.display_name for p in ext.pages}
    return [
        {
            "role": ext.role,
            "page": pages.get(v.page_name, v.page_display_name),
            "page_name": v.page_name,
            "visual_name": v.visual_name,
            "title": v.visual_title or "",
            "type": v.visual_type,
            "status": v.status.value,
            "completeness": v.completeness.value,
            "rows": v.row_count,
            "source": v.source_method.value,
            "extracted_at": v.extracted_at.isoformat(),
            "error": v.error_message or "",
            "truncation": v.truncation_info or "",
            "sha256": (v.raw_sha256 or "")[:16],
        }
        for v in ext.visuals
    ]


def label(ext: ReportExtraction, page_name: str, visual_name: str) -> str:
    v = ext.find(page_name, visual_name)
    if v is None:
        return f"{page_name}/{visual_name}"
    return f"{v.page_display_name} › {v.visual_title or v.visual_name} ({v.visual_type})"
