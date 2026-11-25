"""Read-only FastAPI backend over stored comparison results.

Run:  uvicorn api.main:app --host 127.0.0.1 --port 8000
Exposes history/results/exports for integration. It does NOT expose Power BI
credentials or trigger live extraction (that requires an interactive, signed-in user).
Bind to localhost; put an authenticating reverse proxy in front for any shared deployment.
"""
from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Path, Response

from config.settings import get_settings
from database.repository import Repository
from reporting.csv_export import build_zip
from reporting.excel_export import build_workbook
from reporting.html_report import build_html
from reporting.json_export import build_json

app = FastAPI(title="Power BI Visual Data Comparator API", version="0.1.0",
              description="Read-only access to comparison history and evidence.")
_repo: Repository | None = None


def repo() -> Repository:
    global _repo
    if _repo is None:
        s = get_settings()
        s.ensure_dirs()
        _repo = Repository.from_url(s.database_url)
    return _repo


def _load(run_id: int, r: Repository):
    run = r.load_run(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return run


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "read_only": True}


@app.get("/runs")
def runs(limit: int = 50, r: Repository = Depends(repo)) -> list[dict]:
    return r.list_runs(limit=max(1, min(limit, 500)))


@app.get("/stats")
def stats(r: Repository = Depends(repo)) -> dict:
    return r.stats()


@app.get("/runs/{run_id}")
def run_summary(run_id: int = Path(ge=1), r: Repository = Depends(repo)) -> dict:
    run = _load(run_id, r)
    return {"run_id": run.run_id, "name": run.name, "overall_status": run.overall_status.value,
            "overall_reasons": run.overall_reasons, "is_mock": run.is_mock, "summary": run.summary(),
            "visuals": [{"status": v.status.value, "original": v.original_title, "migrated": v.migrated_title,
                         "reasons": v.reasons, "missing_rows": v.missing_rows, "additional_rows": v.additional_rows,
                         "numeric_mismatches": v.numeric_mismatches} for v in run.visual_results]}


@app.get("/runs/{run_id}/export/{fmt}")
def export(fmt: str, run_id: int = Path(ge=1), r: Repository = Depends(repo)) -> Response:
    run = _load(run_id, r)
    if fmt == "xlsx":
        return Response(build_workbook(run), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    if fmt == "json":
        return Response(build_json(run), media_type="application/json")
    if fmt == "html":
        return Response(build_html(run), media_type="text/html")
    if fmt == "csv":
        return Response(build_zip(run), media_type="application/zip")
    raise HTTPException(400, "fmt must be one of xlsx, json, html, csv")
