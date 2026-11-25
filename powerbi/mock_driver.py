"""MOCK extraction driver — simulates the Power BI JS SDK from a fixture spec.

Used for deterministic tests and the UI's demo mode. Every extraction produced
through this driver is flagged ``is_mock=True`` and ``source_method=MOCK_FIXTURE``.
It must never be presented as live Power BI evidence.

Simulation rules (mirrored by frontend/mock/mock_powerbi.js):
- report/page Basic "In" filters with a single value on the spec's countryTarget
  select the pre-computed CSV for that country; otherwise "__all__".
- spec flags: loadError, getFiltersError, updateFiltersError; visual flags:
  exportError, rowsOverride (synthesises N rows to test truncation), slicerState.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from powerbi.embed_manager import EmbedConfig

FILTER_OPS = {"Add", "Replace"}


def _targets(f: dict[str, Any], target: dict[str, str]) -> bool:
    t = f.get("target") or {}
    return (str(t.get("table", "")).lower() == target["table"].lower()
            and str(t.get("column", "")).lower() == target["column"].lower())


def effective_country(filters: list[dict[str, Any]], target: dict[str, str]) -> str:
    sel: str | None = None
    for f in filters:
        if not _targets(f, target):
            continue
        vals = f.get("values") or []
        if str(f.get("operator", "")).lower() == "in" and len(vals) == 1:
            if sel is not None and sel != vals[0]:
                return "__none__"
            sel = str(vals[0])
    return sel or "__all__"


class MockDriver:
    is_mock = True

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = copy.deepcopy(spec)
        self.report_filters: list[dict[str, Any]] = copy.deepcopy(spec.get("initialReportFilters", []))
        self.active_page: str | None = None
        self.loaded = False
        self.log: list[str] = []
        self.export_calls: list[tuple[str, str, str, int]] = []

    def load_report(self, embed: EmbedConfig, render_timeout_ms: int) -> dict[str, Any]:
        if self.spec.get("loadError"):
            return {"ok": False, "error": self.spec["loadError"]}
        self.loaded = True
        self.active_page = self.spec["pages"][0]["name"]
        self.log.append(f"mock: loaded report {embed.report_id}")
        return {"ok": True, "rendered": True}

    def get_pages(self):
        return [{"name": p["name"], "displayName": p["displayName"], "isActive": p["name"] == self.active_page,
                 "visibility": p.get("visibility", 0)} for p in self.spec["pages"]]

    def activate_page(self, page_name, render_timeout_ms):
        if page_name in self.spec.get("pageActivationErrors", []):
            return {"ok": False, "error": {"message": f"Page {page_name} failed to render"}}
        self.active_page = page_name
        return {"ok": True, "rendered": True}

    def list_visuals(self, page_name):
        return [{"name": v["name"], "type": v["type"], "title": v.get("title"), "layout": v.get("layout", {})}
                for v in self.spec["visuals"].get(page_name, [])]

    def capture_report_filters(self):
        if self.spec.get("getFiltersError"):
            return {"ok": False, "filters": [], "error": {"message": self.spec["getFiltersError"]}}
        return {"ok": True, "filters": copy.deepcopy(self.report_filters)}

    def _page(self, name):
        return next(p for p in self.spec["pages"] if p["name"] == name)

    def capture_page_filters(self, page_name):
        return {"ok": True, "filters": copy.deepcopy(self._page(page_name).get("filters", []))}

    def capture_bookmark_state(self):
        return {"captured": True, "length": 42}

    def update_report_filters(self, operation, filters):
        if operation not in FILTER_OPS:
            return {"ok": False, "error": {"message": f"Operation {operation} refused"}}
        if self.spec.get("updateFiltersError"):
            return {"ok": False, "error": {"message": self.spec["updateFiltersError"]}}
        if operation == "Add":
            self.report_filters.extend(copy.deepcopy(filters))
        else:  # Replace: same data field replaced, otherwise added (documented semantics)
            for nf in filters:
                t = nf.get("target", {})
                idx = next((i for i, f in enumerate(self.report_filters) if f.get("target") == t), None)
                if idx is None:
                    self.report_filters.append(copy.deepcopy(nf))
                else:
                    self.report_filters[idx] = copy.deepcopy(nf)
        return {"ok": True, "rendered": True}

    def _visual(self, page_name, visual_name):
        return next(v for v in self.spec["visuals"][page_name] if v["name"] == visual_name)

    def capture_visual_context(self, page_name, visual_name, is_slicer):
        v = self._visual(page_name, visual_name)
        return {"filters": copy.deepcopy(v.get("filters", [])),
                "slicerState": copy.deepcopy(v.get("slicerState")) if is_slicer else None, "errors": []}

    def export_visual(self, page_name, visual_name, mode, rows):
        self.export_calls.append((page_name, visual_name, mode, rows))
        v = self._visual(page_name, visual_name)
        if v.get("exportError"):
            return {"ok": False, "error": v["exportError"]}
        if mode == "UNDERLYING" and v.get("underlyingError"):
            return {"ok": False, "error": v["underlyingError"]}
        if v.get("rowsOverride"):
            n = min(int(v["rowsOverride"]), rows)
            return {"ok": True, "data": "Item,Value\r\n" + "".join(f"Item {i},{i}\r\n" for i in range(n))}
        csvs = v.get("csvByCountry") or {}
        filters = self.report_filters + self._page(page_name).get("filters", []) + v.get("filters", [])
        key = effective_country(filters, self.spec["countryTarget"])
        if key in csvs:
            data = csvs[key]
        else:
            header = (csvs.get("__all__") or "\r\n").split("\r\n")[0]
            data = header + "\r\n"
        lines = data.split("\r\n")
        if len(lines) - 2 > rows:  # header + trailing empty
            data = "\r\n".join(lines[: rows + 1]) + "\r\n"
        return {"ok": True, "data": data}

    def screenshot(self, path: Path) -> bool:
        return False  # mock: no rendering surface

    def get_log(self):
        return list(self.log)

    def close(self) -> None:
        return None
