"""Fallback extraction via the Execute Queries REST API (docs/TECHNICAL_VALIDATION.md §8.1).

Used ONLY when a visual export fails/unsupported, to retrieve visual-equivalent
aggregated data. Results are labelled ``SourceMethod.FALLBACK_QUERY`` and are capped
at PARTIAL by status_manager unless the user explicitly confirms equivalence.

- DAX is either supplied by the user or built from user-declared group-by columns and
  measure *names*. Measure definitions are never read or compared.
- ``impersonatedUserName`` is never sent (no impersonation; RLS of the caller applies).
- Documented limits: 1 query/call, 1 table, 100,000 rows or 1,000,000 values, 15 MB,
  120 requests/min/user; needs tenant setting + dataset Read & Build permission;
  service principals unsupported for RLS/SSO datasets.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from config.settings import EXECUTE_QUERIES_MAX_ROWS
from core.contracts import Completeness, ExtractionMode, ExtractionStatus, SourceMethod, VisualExtraction, utcnow
from core.security import validate_guid
from powerbi.http_client import PowerBIApiError, PowerBIHttpClient

_READ_QUERY = re.compile(r"^\s*(DEFINE\b[\s\S]*?)?\bEVALUATE\b", re.IGNORECASE)


def q_table(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


def q_col(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


def q_str(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'


@dataclass
class FallbackQuerySpec:
    dataset_workspace_id: str
    dataset_id: str
    dax_query: str | None = None
    group_by: list[tuple[str, str]] = field(default_factory=list)   # (table, column)
    measures: list[tuple[str, str]] = field(default_factory=list)   # (output name, measure name)
    country_filter: tuple[str, str, str] | None = None              # (table, column, value)
    equivalence_confirmed: bool = False

    def query(self) -> str:
        if self.dax_query:
            if not _READ_QUERY.match(self.dax_query):
                raise ValueError("Fallback DAX must be a query starting with EVALUATE (optionally preceded by DEFINE).")
            return self.dax_query
        if not self.measures:
            raise ValueError("Provide a DAX query or at least one measure name.")
        parts = [f"{q_table(t)}{q_col(c)}" for t, c in self.group_by]
        if self.country_filter:
            t, c, v = self.country_filter
            parts.append(f"TREATAS({{{q_str(v)}}}, {q_table(t)}{q_col(c)})")
        parts += [f"{q_str(name)}, {q_col(measure)}" for name, measure in self.measures]
        return "EVALUATE\nSUMMARIZECOLUMNS(\n    " + ",\n    ".join(parts) + "\n)"


def _clean_header(k: str) -> str:
    m = re.match(r"^(?:.*?)\[(.+)\]$", k)
    return m.group(1).replace("]]", "]") if m else k


def rows_to_csv(rows: list[dict]) -> str:
    if not rows:
        return ""
    headers = list(rows[0].keys())
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([_clean_header(h) for h in headers])
    for r in rows:
        w.writerow(["" if r.get(h) is None else r.get(h) for h in headers])
    return buf.getvalue()


class ExecuteQueriesFallback:
    def __init__(self, http: PowerBIHttpClient) -> None:
        self.http = http

    def extract(self, spec: FallbackQuerySpec, template: VisualExtraction) -> VisualExtraction:
        """Return a FALLBACK_QUERY VisualExtraction for the visual described by ``template``."""
        base = template.model_dump(exclude={"raw_csv", "raw_sha256", "status", "completeness", "source_method",
                                            "row_count", "rows_requested", "error_code", "error_message", "truncation_info",
                                            "extracted_at", "fallback_equivalence_confirmed", "extraction_mode"})
        common = dict(**base, source_method=SourceMethod.FALLBACK_QUERY, extraction_mode=ExtractionMode.SUMMARIZED,
                      extracted_at=utcnow(), fallback_equivalence_confirmed=spec.equivalence_confirmed)
        try:
            ws = validate_guid(spec.dataset_workspace_id, "dataset workspace id")
            ds = validate_guid(spec.dataset_id, "dataset id")
            query = spec.query()
        except ValueError as exc:
            return VisualExtraction(**common, status=ExtractionStatus.FAILED, completeness=Completeness.INCOMPLETE,
                                    error_code="fallback_config", error_message=str(exc))
        payload = {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}
        try:
            resp = self.http.post_readonly(f"/groups/{ws}/datasets/{ds}/executeQueries", payload)
        except PowerBIApiError as exc:
            return VisualExtraction(**common, status=ExtractionStatus.FAILED, completeness=Completeness.INCOMPLETE,
                                    error_code=exc.code or exc.category.value, error_message=f"{exc.friendly} {exc.detail}")
        err = resp.get("error") or ((resp.get("results") or [{}])[0].get("error"))
        tables = (resp.get("results") or [{}])[0].get("tables") or []
        if err or not tables or tables[0].get("error"):
            e = err or (tables[0].get("error") if tables else {"message": "no table returned"})
            return VisualExtraction(**common, status=ExtractionStatus.FAILED, completeness=Completeness.INCOMPLETE,
                                    error_code=str(e.get("code") or "query_error"), error_message=str(e.get("message") or e))
        rows = tables[0].get("rows") or []
        n = len(rows)
        cols = len(rows[0]) if rows else 0
        limit = min(EXECUTE_QUERIES_MAX_ROWS, 1_000_000 // cols) if cols else EXECUTE_QUERIES_MAX_ROWS
        status, completeness, trunc = ExtractionStatus.SUCCESS, Completeness.COMPLETE, None
        if n >= limit:
            status, completeness = ExtractionStatus.POSSIBLY_TRUNCATED, Completeness.UNKNOWN
            trunc = f"{n} rows reached the documented Execute Queries limit ({limit}); completeness not established."
        note = "FALLBACK reconstructed query data (not a visual export). Query: " + query.replace("\n", " ")[:500]
        return VisualExtraction(**common, status=status, completeness=completeness, row_count=n,
                                rows_requested=limit, raw_csv=rows_to_csv(rows) if rows else "",
                                truncation_info=(trunc + " " if trunc else "") + note)
