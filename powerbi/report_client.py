"""Report and page discovery (verified endpoints: TECHNICAL_VALIDATION.md §7)."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.contracts import PageInfo, ReportInfo
from core.security import validate_guid
from powerbi.http_client import PowerBIApiError, PowerBIHttpClient


@dataclass
class AccessValidation:
    ok: bool
    report: ReportInfo | None = None
    pages: list[PageInfo] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ReportClient:
    def __init__(self, http: PowerBIHttpClient) -> None:
        self.http = http

    def list_reports(self, workspace_id: str, include_paginated: bool = False) -> list[ReportInfo]:
        wid = validate_guid(workspace_id, "workspace id")
        items = self.http.get_all(f"/groups/{wid}/reports")
        reports = [self._map(i, wid) for i in items]
        if not include_paginated:
            reports = [r for r in reports if (r.report_type or "PowerBIReport") == "PowerBIReport"]
        return sorted(reports, key=lambda r: r.name.lower())

    def get_report(self, workspace_id: str, report_id: str) -> ReportInfo:
        wid = validate_guid(workspace_id, "workspace id")
        rid = validate_guid(report_id, "report id")
        return self._map(self.http.get(f"/groups/{wid}/reports/{rid}"), wid)

    def list_pages(self, workspace_id: str, report_id: str) -> list[PageInfo]:
        wid = validate_guid(workspace_id, "workspace id")
        rid = validate_guid(report_id, "report id")
        items = self.http.get_all(f"/groups/{wid}/reports/{rid}/pages")
        pages = [
            PageInfo(name=i["name"], display_name=i.get("displayName") or i["name"], order=_to_int(i.get("order")))
            for i in items
        ]
        return sorted(pages, key=lambda p: (p.order is None, p.order or 0, p.display_name))

    def validate_access(self, workspace_id: str, report_id: str) -> AccessValidation:
        """Validate the identity can read the report & its pages. Never raises for API errors."""
        result = AccessValidation(ok=False)
        try:
            result.report = self.get_report(workspace_id, report_id)
        except ValueError as exc:
            result.problems.append(str(exc))
            return result
        except PowerBIApiError as exc:
            result.problems.append(f"Report: {exc.friendly}")
            return result
        try:
            result.pages = self.list_pages(workspace_id, report_id)
        except PowerBIApiError as exc:
            result.problems.append(f"Pages: {exc.friendly}")
            return result
        if result.report.report_type and result.report.report_type != "PowerBIReport":
            result.problems.append(f"Report type {result.report.report_type} is not supported (visual export requires a Power BI report).")
        if not result.report.embed_url:
            result.problems.append("Report has no embedUrl; it cannot be embedded for extraction.")
        if not result.report.dataset_id:
            result.warnings.append("datasetId not returned; fallback queries will be unavailable.")
        if not result.pages:
            result.problems.append("Report has no pages visible to this identity.")
        result.ok = not result.problems
        return result

    @staticmethod
    def _map(i: dict, workspace_id: str) -> ReportInfo:
        return ReportInfo(
            id=i["id"],
            name=i.get("name", ""),
            workspace_id=workspace_id,
            dataset_id=i.get("datasetId"),
            embed_url=i.get("embedUrl"),
            web_url=i.get("webUrl"),
            report_type=i.get("reportType"),
            format=i.get("format"),
        )


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
