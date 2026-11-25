"""Visual extraction engine.

``VisualExtractor`` orchestrates a report extraction through an
``ExtractionDriver``. Two drivers exist:

- ``PlaywrightDriver`` — LIVE path: drives Chromium hosting frontend/embed_host.html
  (official powerbi-client SDK) and calls window.pbiExtractor primitives.
- ``MockDriver`` (powerbi/mock_driver.py) — MOCK path for tests/demo only.

All decision logic (classification, truncation, completeness, context
validation) is here so it is identical for both drivers and unit-testable.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from config.settings import EXPORT_DATA_MAX_ROWS
from core.contracts import (
    Completeness,
    CountryContextConfig,
    ExtractionMode,
    ExtractionStatus,
    PageInfo,
    ReportExtraction,
    ReportInfo,
    SourceMethod,
    VisualExtraction,
    parse_export_csv,
    utcnow,
)
from core.security import get_logger, safe_join, sanitize
from powerbi import filter_manager as fm
from powerbi.embed_manager import EmbedConfig

log = get_logger("powerbi.extractor")

# Visual type names as they appear in VisualDescriptor.type. Used only for
# classification/labels; unknown types are still attempted (never assumed).
NON_DATA_TYPES = {
    "textbox", "shape", "basicShape", "image", "actionButton", "button", "pageNavigator",
    "bookmarkNavigator", "group", "visualGroup",
}
SLICER_TYPES = {"slicer", "advancedSlicerVisual", "listSlicer", "textSlicer"}
UNSUPPORTED_TYPES = {
    "scriptVisual": "R visuals are not supported by exportData (documented).",
    "pythonVisual": "Python script visuals are not supported for programmatic export (R/custom documented; Python treated the same).",
}
KNOWN_DATA_TYPES = {
    "card", "cardVisual", "multiRowCard", "tableEx", "pivotTable", "clusteredBarChart", "clusteredColumnChart",
    "stackedBarChart", "stackedColumnChart", "hundredPercentStackedBarChart", "hundredPercentStackedColumnChart",
    "lineChart", "areaChart", "stackedAreaChart", "lineClusteredColumnComboChart", "lineStackedColumnComboChart",
    "pieChart", "donutChart", "treemap", "waterfallChart", "funnel", "scatterChart", "gauge", "kpi", "map",
    "filledMap", "ribbonChart", "decompositionTreeVisual",
}
_CUSTOM_VISUAL_RE = re.compile(r"^[A-Za-z]+[0-9A-F]{20,}$|PBI_CV_", re.IGNORECASE)

ProgressCb = Callable[[str, str, dict[str, Any]], None]


class ExtractionDriver(Protocol):
    is_mock: bool

    def load_report(self, embed: EmbedConfig, render_timeout_ms: int) -> dict[str, Any]: ...
    def get_pages(self) -> list[dict[str, Any]]: ...
    def activate_page(self, page_name: str, render_timeout_ms: int) -> dict[str, Any]: ...
    def list_visuals(self, page_name: str) -> list[dict[str, Any]]: ...
    def capture_report_filters(self) -> dict[str, Any]: ...
    def capture_page_filters(self, page_name: str) -> dict[str, Any]: ...
    def capture_bookmark_state(self) -> dict[str, Any]: ...
    def update_report_filters(self, operation: str, filters: list[dict[str, Any]]) -> dict[str, Any]: ...
    def capture_visual_context(self, page_name: str, visual_name: str, is_slicer: bool) -> dict[str, Any]: ...
    def export_visual(self, page_name: str, visual_name: str, mode: str, rows: int) -> dict[str, Any]: ...
    def screenshot(self, path: Path) -> bool: ...
    def get_log(self) -> list[str]: ...
    def close(self) -> None: ...


def classify_visual(vtype: str) -> tuple[str, str | None]:
    """Return (category, reason). category in data|slicer|non_data|unsupported|unknown."""
    if vtype in SLICER_TYPES:
        return "slicer", "Slicer: not a data visual; state captured as context evidence."
    if vtype in NON_DATA_TYPES:
        return "non_data", f"Non-data visual type '{vtype}'."
    if vtype in UNSUPPORTED_TYPES:
        return "unsupported", UNSUPPORTED_TYPES[vtype]
    if vtype in KNOWN_DATA_TYPES:
        return "data", None
    if _CUSTOM_VISUAL_RE.search(vtype or ""):
        return "unknown", "Looks like a custom (AppSource/organizational) visual; custom visuals are not supported by exportData (documented). Export attempted to confirm."
    return "unknown", f"Unrecognised visual type '{vtype}'; export attempted."


def _err_text(err: dict[str, Any] | None) -> str:
    if not err:
        return "unknown error"
    parts = [str(err.get("message") or "")]
    if err.get("detailedMessage") and err.get("detailedMessage") != err.get("message"):
        parts.append(str(err["detailedMessage"]))
    return sanitize(" — ".join(p for p in parts if p))[:1000]


class VisualExtractor:
    def __init__(
        self,
        driver: ExtractionDriver,
        render_timeout_ms: int = 90_000,
        rows: int = EXPORT_DATA_MAX_ROWS,
        screenshot_dir: Path | None = None,
        progress: ProgressCb | None = None,
    ) -> None:
        self.driver = driver
        self.render_timeout_ms = render_timeout_ms
        self.rows = min(rows, EXPORT_DATA_MAX_ROWS)
        self.screenshot_dir = screenshot_dir
        self._progress = progress or (lambda stage, msg, data: None)

    def _p(self, stage: str, msg: str, **data: Any) -> None:
        log.info("[%s] %s", stage, msg)
        self._progress(stage, msg, data)

    def extract(
        self,
        role: str,
        report: ReportInfo,
        embed: EmbedConfig,
        country: CountryContextConfig,
        apply_context: bool,
        mode: ExtractionMode = ExtractionMode.SUMMARIZED,
        page_filter: set[str] | None = None,
    ) -> ReportExtraction:
        table = country.original_table if role == "original" else country.migrated_table
        column = country.original_column if role == "original" else country.migrated_column
        ext = ReportExtraction(
            role=role, workspace_id=report.workspace_id, report_id=report.id, report_name=report.name,
            dataset_id=report.dataset_id, is_mock=self.driver.is_mock,
        )
        ext.log.extend(embed.notes)
        if self.driver.is_mock:
            ext.log.append("MOCK DRIVER: data comes from fixtures, not from Power BI.")

        self._p("report_loading", f"Loading {role} report '{report.name}'")
        res = self.driver.load_report(embed, self.render_timeout_ms)
        if not res.get("ok"):
            ext.fatal_error = f"Report load failed: {_err_text(res.get('error'))}"
            ext.log.append(ext.fatal_error)
            ext.context = fm.validate_context(fm.ContextInputs(
                required=apply_context, table=table, column=column, value=country.value, before=[], after=[],
                capture_errors=["report not loaded"]))
            ext.finished_at = utcnow()
            self._p("report_loading", ext.fatal_error, failed=True)
            return ext
        if not res.get("rendered"):
            ext.log.append("Report 'rendered' event not observed within timeout.")

        self._p("page_discovery", "Discovering pages")
        raw_pages = self.driver.get_pages()
        ext.pages = [PageInfo(name=p["name"], display_name=p.get("displayName") or p["name"], order=i)
                     for i, p in enumerate(raw_pages)]
        hidden = {p["name"] for p in raw_pages if p.get("visibility") == 1}

        # ---- filter context: capture -> plan -> apply -> capture
        self._p("filter_application", "Capturing filter context")
        capture_errors: list[str] = []
        before = self.driver.capture_report_filters()
        if not before.get("ok"):
            capture_errors.append(f"report filters (before): {_err_text(before.get('error'))}")
        bookmark = self.driver.capture_bookmark_state()
        plan = None
        apply_failed = None
        if apply_context:
            if not table or not column:
                apply_failed = "country field (table/column) not configured"
            else:
                plan = fm.plan_context(before.get("filters", []), table, column, country.value,
                                       country.allow_replace_conflicting)
                if plan.action in ("add", "replace"):
                    op = "Add" if plan.action == "add" else "Replace"
                    r = self.driver.update_report_filters(op, [plan.filter])
                    if not r.get("ok"):
                        apply_failed = _err_text(r.get("error"))
                    self._p("filter_application", f"Applied context via {op}: {country.value}", ok=r.get("ok"))
        after = self.driver.capture_report_filters()
        if not after.get("ok"):
            capture_errors.append(f"report filters (after): {_err_text(after.get('error'))}")

        # ---- pages & visuals
        page_filters: dict[str, list[dict[str, Any]]] = {}
        slicer_states: list[dict[str, Any]] = []
        for page in ext.pages:
            if page_filter and page.name not in page_filter:
                continue
            self._p("visual_discovery", f"Page '{page.display_name}'")
            act = self.driver.activate_page(page.name, self.render_timeout_ms)
            render_ok = bool(act.get("ok") and act.get("rendered"))
            if not act.get("ok"):
                ext.log.append(f"Page '{page.display_name}' activation failed: {_err_text(act.get('error'))}")
            pf = self.driver.capture_page_filters(page.name)
            page_filters[page.name] = pf.get("filters", [])
            if not pf.get("ok"):
                capture_errors.append(f"page filters '{page.display_name}': {_err_text(pf.get('error'))}")
            try:
                visuals = self.driver.list_visuals(page.name)
            except Exception as exc:  # enumerate failure is recorded, never silent
                ext.log.append(f"Visual enumeration failed on page '{page.display_name}': {sanitize(str(exc))}")
                ext.visuals.append(VisualExtraction(
                    workspace_id=report.workspace_id, report_id=report.id, page_name=page.name,
                    page_display_name=page.display_name, visual_name="__page_enumeration__", visual_type="unknown",
                    status=ExtractionStatus.FAILED, completeness=Completeness.INCOMPLETE,
                    error_code="enumeration_failed", error_message=sanitize(str(exc))))
                continue
            if page.name in hidden:
                ext.log.append(f"Page '{page.display_name}' is hidden; visuals still enumerated.")
            if self.screenshot_dir is not None:
                self._screenshot(ext, page)
            for v in visuals:
                ext.visuals.append(self._extract_visual(report, page, v, mode, render_ok, slicer_states))

        ext.context = fm.validate_context(fm.ContextInputs(
            required=apply_context, table=table, column=column, value=country.value,
            before=before.get("filters", []), after=after.get("filters", []), page_filters=page_filters,
            slicer_states=slicer_states, plan=plan, apply_failed=apply_failed, capture_errors=capture_errors,
            bookmark_captured=bool(bookmark.get("captured")),
        ))
        ext.log.extend(sanitize(x) for x in self.driver.get_log())
        ext.finished_at = utcnow()
        c = ext.counts()
        self._p("visual_extraction", f"{role}: {c['SUCCESS']} ok, {c['FAILED']} failed, {c['UNSUPPORTED']} unsupported, "
                f"{c['POSSIBLY_TRUNCATED']} possibly truncated", counts=c, context=ext.context.status.value)
        return ext

    # ------------------------------------------------------------------ per visual
    def _extract_visual(self, report: ReportInfo, page: PageInfo, v: dict[str, Any], mode: ExtractionMode,
                        render_ok: bool, slicer_states: list[dict[str, Any]]) -> VisualExtraction:
        vtype = v.get("type") or "unknown"
        base = dict(
            workspace_id=report.workspace_id, report_id=report.id, page_name=page.name,
            page_display_name=page.display_name, visual_name=v["name"], visual_type=vtype,
            visual_title=v.get("title"), extraction_mode=mode, layout=v.get("layout") or {},
            source_method=SourceMethod.MOCK_FIXTURE if self.driver.is_mock else SourceMethod.VISUAL_EXPORT,
        )
        category, reason = classify_visual(vtype)
        if category == "slicer":
            ctx = self.driver.capture_visual_context(page.name, v["name"], True)
            slicer_states.append({"page": page.name, "visual": v["name"], "title": v.get("title"), "state": ctx.get("slicerState")})
            return VisualExtraction(**base, status=ExtractionStatus.SKIPPED_NON_DATA, completeness=Completeness.COMPLETE,
                                    visual_filters=ctx.get("filters", []), error_message=reason)
        if category == "non_data":
            return VisualExtraction(**base, status=ExtractionStatus.SKIPPED_NON_DATA, completeness=Completeness.COMPLETE, error_message=reason)
        if category == "unsupported":
            return VisualExtraction(**base, status=ExtractionStatus.UNSUPPORTED, completeness=Completeness.INCOMPLETE,
                                    error_code="unsupported_visual_type", error_message=reason)

        ctx = self.driver.capture_visual_context(page.name, v["name"], False)
        self._p("visual_extraction", f"Exporting '{v.get('title') or v['name']}' ({vtype})")
        res = self.driver.export_visual(page.name, v["name"], mode.value, self.rows)
        extracted_at = datetime.now(timezone.utc)
        if not res.get("ok"):
            err = res.get("error") or {}
            status = ExtractionStatus.UNSUPPORTED if category == "unknown" else ExtractionStatus.FAILED
            msg = _err_text(err)
            if category == "unknown" and reason:
                msg = f"{reason} Export error: {msg}"
            return VisualExtraction(**base, extracted_at=extracted_at, status=status, completeness=Completeness.INCOMPLETE,
                                    rows_requested=self.rows, error_code=str(err.get("errorCode") or "export_failed"),
                                    error_message=msg, visual_filters=ctx.get("filters", []))
        raw = res.get("data")
        if raw is None or not str(raw).strip():
            return VisualExtraction(**base, extracted_at=extracted_at, status=ExtractionStatus.FAILED,
                                    completeness=Completeness.INCOMPLETE, rows_requested=self.rows, raw_csv=raw,
                                    error_code="empty_export", error_message="Export returned empty content (no header).",
                                    visual_filters=ctx.get("filters", []))
        try:
            n = len(parse_export_csv(raw))
        except Exception as exc:
            return VisualExtraction(**base, extracted_at=extracted_at, status=ExtractionStatus.FAILED,
                                    completeness=Completeness.INCOMPLETE, rows_requested=self.rows, raw_csv=raw,
                                    error_code="csv_parse_error", error_message=sanitize(str(exc))[:500],
                                    visual_filters=ctx.get("filters", []))
        status = ExtractionStatus.SUCCESS
        completeness = Completeness.COMPLETE
        trunc = None
        if n >= self.rows:
            status = ExtractionStatus.POSSIBLY_TRUNCATED
            completeness = Completeness.UNKNOWN
            trunc = f"Returned {n} rows = requested/maximum {self.rows} (documented exportData limit 30,000). Completeness not established."
        elif not render_ok:
            completeness = Completeness.UNKNOWN
            trunc = "Page render completion not confirmed before export; completeness not established."
        notes = f"Unrecognised type exported successfully. {reason}" if category == "unknown" else None
        return VisualExtraction(**base, extracted_at=extracted_at, status=status, completeness=completeness, row_count=n,
                                rows_requested=self.rows, raw_csv=raw, truncation_info=trunc or notes,
                                visual_filters=ctx.get("filters", []))

    def _screenshot(self, ext: ReportExtraction, page: PageInfo) -> None:
        try:
            path = safe_join(self.screenshot_dir, f"{ext.role}_{ext.report_id[:8]}_{page.name}.png")
            if self.driver.screenshot(path):
                ext.log.append(f"Screenshot captured: {path.name}")
        except Exception as exc:
            ext.log.append(f"Screenshot failed for page '{page.display_name}': {sanitize(str(exc))}")


class PlaywrightDriver:
    """LIVE driver: Chromium + official powerbi-client SDK. Requires network access to Power BI."""

    is_mock = False

    def __init__(self, host_url: str, headless: bool = True, init_script: str | None = None,
                 html_page: str = "embed_host.html", is_mock: bool = False) -> None:
        from playwright.sync_api import sync_playwright

        self.is_mock = is_mock
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        self._context = self._browser.new_context(viewport={"width": 1680, "height": 1000})
        if init_script:
            self._context.add_init_script(init_script)
        self.page = self._context.new_page()
        self.page.goto(f"{host_url}/{html_page}")
        self.page.wait_for_function("() => window.pbiExtractor !== undefined", timeout=30_000)

    def _call(self, fn: str, *args: Any, timeout_ms: int | None = None) -> Any:
        if timeout_ms:
            self.page.set_default_timeout(timeout_ms)
        return self.page.evaluate(f"(args) => window.pbiExtractor.{fn}(...args)", list(args))

    def load_report(self, embed: EmbedConfig, render_timeout_ms: int) -> dict[str, Any]:
        return self._call("loadReport", embed.to_js(render_timeout_ms), timeout_ms=render_timeout_ms * 2 + 10_000)

    def get_pages(self):
        return self._call("getPages")

    def activate_page(self, page_name, render_timeout_ms):
        return self._call("activatePage", page_name, render_timeout_ms)

    def list_visuals(self, page_name):
        return self._call("listVisuals", page_name)

    def capture_report_filters(self):
        return self._call("captureReportFilters")

    def capture_page_filters(self, page_name):
        return self._call("capturePageFilters", page_name)

    def capture_bookmark_state(self):
        return self._call("captureBookmarkState")

    def update_report_filters(self, operation, filters):
        return self._call("updateReportFilters", operation, filters)

    def capture_visual_context(self, page_name, visual_name, is_slicer):
        return self._call("captureVisualContext", page_name, visual_name, is_slicer)

    def export_visual(self, page_name, visual_name, mode, rows):
        return self._call("exportVisual", page_name, visual_name, mode, rows)

    def screenshot(self, path: Path) -> bool:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.page.locator("#reportContainer").screenshot(path=str(path))
        return True

    def get_log(self):
        return self._call("getLog")

    def close(self) -> None:
        try:
            self._context.close()
            self._browser.close()
        finally:
            self._pw.stop()
