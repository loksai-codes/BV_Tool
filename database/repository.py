"""Persistence API. All queries go through the SQLAlchemy ORM/Core with bound
parameters (no string-built SQL), which protects against SQL injection."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Engine, create_engine, delete, event, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from core.contracts import (
    ComparisonConfig,
    ComparisonRunResult,
    ComparisonStatus,
    Completeness,
    ExtractionMode,
    ExtractionStatus,
    FilterContextEvidence,
    PageInfo,
    ReportExtraction,
    SourceMethod,
    VisualComparisonResult,
    VisualExtraction,
    VisualMapping,
)
from core.security import sanitize
from database.migrations.migrate import upgrade
from database.models import (
    AuditLog,
    ColumnMappingRow,
    ComparisonSession,
    ExtractedVisual,
    ExtractedVisualData,
    ExtractionRun,
    FilterConfiguration,
    MappingProfile,
    MismatchRow,
    PageMappingRow,
    ReconciliationResultRow,
    ReportSelection,
    Screenshot,
    UserRef,
    VisualMappingRow,
    WorkspaceRef,
)


def make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _):  # enforce FK constraints in SQLite
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    return engine


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


class Repository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        upgrade(engine)
        self._Session = sessionmaker(engine, expire_on_commit=False)

    @classmethod
    def from_url(cls, url: str) -> "Repository":
        return cls(make_engine(url))

    # ------------------------------------------------------------------ users & audit
    def user_ref(self, account: str | None, label: str | None = None) -> int | None:
        if not account:
            return None
        h = hashlib.sha256(account.lower().encode("utf-8")).hexdigest()
        with self._Session.begin() as s:
            row = s.scalar(select(UserRef).where(UserRef.account_hash == h))
            if row is None:
                row = UserRef(account_hash=h, display_label=label)
                s.add(row)
                s.flush()
            return row.id

    def audit(self, action: str, detail: str = "", actor_ref_id: int | None = None) -> None:
        with self._Session.begin() as s:
            s.add(AuditLog(action=action[:100], detail=sanitize(detail)[:4000], actor_ref_id=actor_ref_id))

    def audit_entries(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._Session() as s:
            rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)).all()
            return [{"ts": r.ts, "action": r.action, "detail": r.detail} for r in rows]

    # ------------------------------------------------------------------ save run
    def save_run(self, run: ComparisonRunResult, actor_ref_id: int | None = None) -> int:
        cfg = run.config
        with self._Session.begin() as s:
            sess = ComparisonSession(
                name=run.name,
                user_ref_id=actor_ref_id,
                overall_status=run.overall_status.value,
                overall_reasons=list(run.overall_reasons),
                config_json=cfg.model_dump(mode="json"),
                summary_json=run.summary(),
                is_mock=run.is_mock,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            s.add(sess)
            for ext in (run.original, run.migrated):
                sess.workspaces.append(WorkspaceRef(role=ext.role, workspace_id=ext.workspace_id))
                sess.reports.append(
                    ReportSelection(
                        role=ext.role, workspace_id=ext.workspace_id, report_id=ext.report_id,
                        report_name=ext.report_name, dataset_id=ext.dataset_id,
                    )
                )
                sess.extraction_runs.append(self._extraction_row(ext))
            for pm in cfg.page_mappings:
                sess.page_mappings.append(
                    PageMappingRow(original_page=pm.original_page, migrated_page=pm.migrated_page,
                                   confidence=pm.confidence, provenance=pm.provenance, approved=pm.approved)
                )
            for vm in cfg.visual_mappings:
                sess.visual_mappings.append(self._visual_mapping_row(vm))
            sess.filter_configs.append(FilterConfiguration(config_json=cfg.country.model_dump(mode="json")))
            for vr in run.visual_results:
                row = ReconciliationResultRow(
                    original_page=vr.original_page, original_visual=vr.original_visual,
                    migrated_page=vr.migrated_page, migrated_visual=vr.migrated_visual,
                    status=vr.status.value, reasons_json=list(vr.reasons),
                    rows_compared=vr.rows_compared, missing_rows=vr.missing_rows,
                    additional_rows=vr.additional_rows, numeric_mismatches=vr.numeric_mismatches,
                    result_json=vr.model_dump(mode="json", exclude={"mismatches"}),
                )
                for m in vr.mismatches:
                    row.mismatches.append(
                        MismatchRow(
                            mismatch_type=m.mismatch_type.value, key_json=_jsonable(m.key), column=m.column,
                            original_value=_s(m.original_value), migrated_value=_s(m.migrated_value),
                            absolute_difference=_s(m.absolute_difference),
                            percentage_difference=_s(m.percentage_difference),
                            confirmed=m.confirmed,
                            detail=(m.detail + (f" [{m.percentage_note}]" if m.percentage_note else "")) or None,
                        )
                    )
                sess.results.append(row)
            s.flush()
            sid = sess.id
            s.add(AuditLog(action="comparison_saved", actor_ref_id=actor_ref_id,
                           detail=f"session={sid} status={run.overall_status.value} mock={run.is_mock}"))
        return sid

    @staticmethod
    def _visual_mapping_row(vm: VisualMapping) -> VisualMappingRow:
        row = VisualMappingRow(
            original_page=vm.original_page, original_visual=vm.original_visual,
            migrated_page=vm.migrated_page, migrated_visual=vm.migrated_visual,
            confidence=vm.confidence, provenance=vm.provenance, approved=vm.approved,
            mandatory=vm.mandatory, signals_json=dict(vm.signals), key_columns=list(vm.key_columns),
        )
        for cm in vm.column_mappings:
            row.columns.append(ColumnMappingRow(original=cm.original, migrated=cm.migrated, role=cm.role, provenance=cm.provenance))
        return row

    @staticmethod
    def _extraction_row(ext: ReportExtraction) -> ExtractionRun:
        run = ExtractionRun(
            role=ext.role, workspace_id=ext.workspace_id, report_id=ext.report_id, report_name=ext.report_name,
            dataset_id=ext.dataset_id, pages_json=[p.model_dump() for p in ext.pages],
            context_json=ext.context.model_dump(mode="json"), counts_json=ext.counts(),
            log_json=[sanitize(x) for x in ext.log], fatal_error=ext.fatal_error, is_mock=ext.is_mock,
            started_at=ext.started_at, finished_at=ext.finished_at,
        )
        for v in ext.visuals:
            ev = ExtractedVisual(
                page_name=v.page_name, page_display_name=v.page_display_name, visual_name=v.visual_name,
                visual_type=v.visual_type, visual_title=v.visual_title, extraction_mode=v.extraction_mode.value,
                extracted_at=v.extracted_at, status=v.status.value, completeness=v.completeness.value,
                source_method=v.source_method.value, row_count=v.row_count, rows_requested=v.rows_requested,
                error_code=v.error_code, error_message=v.error_message, truncation_info=v.truncation_info,
                filters_json=v.visual_filters, layout_json=v.layout, screenshot_path=v.screenshot_path,
                fallback_equivalence_confirmed=v.fallback_equivalence_confirmed,
            )
            if v.raw_csv is not None:
                ev.data = ExtractedVisualData(raw_csv=v.raw_csv, sha256=v.raw_sha256 or "",
                                              byte_size=len(v.raw_csv.encode("utf-8")))
            run.visuals.append(ev)
        return run

    # ------------------------------------------------------------------ read
    def list_runs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._Session() as s:
            rows = s.scalars(select(ComparisonSession).order_by(ComparisonSession.id.desc()).limit(limit)).all()
            return [
                {
                    "id": r.id, "name": r.name, "overall_status": r.overall_status, "is_mock": r.is_mock,
                    "started_at": r.started_at, "finished_at": r.finished_at, **(r.summary_json or {}),
                }
                for r in rows
            ]

    def stats(self) -> dict[str, Any]:
        with self._Session() as s:
            total = s.scalar(select(func.count(ComparisonSession.id))) or 0
            last = s.scalar(select(ComparisonSession).order_by(ComparisonSession.id.desc()).limit(1))
            visuals = s.scalar(select(func.count(ReconciliationResultRow.id))) or 0
            mismatches = s.scalar(select(func.count(MismatchRow.id))) or 0
            return {
                "total_runs": total,
                "last_run_at": last.started_at if last else None,
                "last_status": last.overall_status if last else None,
                "last_is_mock": last.is_mock if last else None,
                "total_visuals_compared": visuals,
                "total_mismatches": mismatches,
            }

    def load_run(self, session_id: int) -> ComparisonRunResult | None:
        with self._Session() as s:
            sess = s.scalar(
                select(ComparisonSession)
                .where(ComparisonSession.id == session_id)
                .options(
                    selectinload(ComparisonSession.extraction_runs).selectinload(ExtractionRun.visuals).selectinload(ExtractedVisual.data),
                    selectinload(ComparisonSession.results).selectinload(ReconciliationResultRow.mismatches),
                )
            )
            if sess is None:
                return None
            exts = {r.role: self._extraction_from_row(r) for r in sess.extraction_runs}
            results = []
            for r in sess.results:
                data = dict(r.result_json)
                data["mismatches"] = [
                    {
                        "mismatch_type": m.mismatch_type, "key": m.key_json, "column": m.column,
                        "original_value": m.original_value, "migrated_value": m.migrated_value,
                        "absolute_difference": m.absolute_difference, "percentage_difference": m.percentage_difference,
                        "confirmed": m.confirmed, "detail": m.detail or "",
                    }
                    for m in r.mismatches
                ]
                results.append(VisualComparisonResult.model_validate(data))
            return ComparisonRunResult(
                run_id=sess.id, name=sess.name, overall_status=ComparisonStatus(sess.overall_status),
                overall_reasons=list(sess.overall_reasons or []), started_at=sess.started_at,
                finished_at=sess.finished_at, is_mock=sess.is_mock,
                config=ComparisonConfig.model_validate(sess.config_json),
                original=exts["original"], migrated=exts["migrated"], visual_results=results,
            )

    @staticmethod
    def _extraction_from_row(r: ExtractionRun) -> ReportExtraction:
        visuals = [
            VisualExtraction(
                workspace_id=r.workspace_id, report_id=r.report_id, page_name=v.page_name,
                page_display_name=v.page_display_name, visual_name=v.visual_name, visual_type=v.visual_type,
                visual_title=v.visual_title, extraction_mode=ExtractionMode(v.extraction_mode),
                extracted_at=v.extracted_at, status=ExtractionStatus(v.status),
                completeness=Completeness(v.completeness), source_method=SourceMethod(v.source_method),
                row_count=v.row_count, rows_requested=v.rows_requested,
                raw_csv=v.data.raw_csv if v.data else None, raw_sha256=v.data.sha256 if v.data else None,
                error_code=v.error_code, error_message=v.error_message, truncation_info=v.truncation_info,
                visual_filters=v.filters_json or [], layout=v.layout_json or {}, screenshot_path=v.screenshot_path,
                fallback_equivalence_confirmed=v.fallback_equivalence_confirmed,
            )
            for v in r.visuals
        ]
        return ReportExtraction(
            role=r.role, workspace_id=r.workspace_id, report_id=r.report_id, report_name=r.report_name,
            dataset_id=r.dataset_id, pages=[PageInfo.model_validate(p) for p in r.pages_json or []],
            visuals=visuals, context=FilterContextEvidence.model_validate(r.context_json or {}),
            started_at=r.started_at, finished_at=r.finished_at, is_mock=r.is_mock,
            log=list(r.log_json or []), fatal_error=r.fatal_error,
        )

    # ------------------------------------------------------------------ mapping profiles
    def save_mapping_profile(self, name: str, original_report_id: str, migrated_report_id: str,
                             page_mappings: list, visual_mappings: list) -> int:
        payload = {
            "page_mappings": [p.model_dump(mode="json") for p in page_mappings],
            "visual_mappings": [v.model_dump(mode="json") for v in visual_mappings if v.approved],
        }
        with self._Session.begin() as s:
            row = s.scalar(select(MappingProfile).where(
                MappingProfile.original_report_id == original_report_id,
                MappingProfile.migrated_report_id == migrated_report_id,
                MappingProfile.name == name))
            if row is None:
                row = MappingProfile(name=name, original_report_id=original_report_id,
                                     migrated_report_id=migrated_report_id, mappings_json=payload)
                s.add(row)
            else:
                row.mappings_json = payload
            s.flush()
            return row.id

    def load_mapping_profiles(self, original_report_id: str, migrated_report_id: str) -> list[dict[str, Any]]:
        with self._Session() as s:
            rows = s.scalars(select(MappingProfile).where(
                MappingProfile.original_report_id == original_report_id,
                MappingProfile.migrated_report_id == migrated_report_id)).all()
            return [{"id": r.id, "name": r.name, "updated_at": r.updated_at, **r.mappings_json} for r in rows]

    # ------------------------------------------------------------------ screenshots & retention
    def add_screenshot(self, path: str, sha256: str, extraction_run_id: int | None = None,
                       page_name: str | None = None, visual_name: str | None = None) -> int:
        with self._Session.begin() as s:
            row = Screenshot(path=path, sha256=sha256, extraction_run_id=extraction_run_id,
                             page_name=page_name, visual_name=visual_name)
            s.add(row)
            s.flush()
            return row.id

    def purge_older_than(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        with self._Session.begin() as s:
            ids = s.scalars(select(ComparisonSession.id).where(ComparisonSession.started_at < cutoff)).all()
            for sid in ids:
                obj = s.get(ComparisonSession, sid)
                if obj is not None:
                    s.delete(obj)
            s.add(AuditLog(action="retention_purge", detail=f"removed={len(ids)} older_than_days={days}"))
            return len(ids)

    def delete_run(self, session_id: int) -> bool:
        with self._Session.begin() as s:
            obj = s.get(ComparisonSession, session_id)
            if obj is None:
                return False
            s.delete(obj)
            s.add(AuditLog(action="run_deleted", detail=f"session={session_id}"))
            return True


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {str(k): (None if v is None else str(v)) for k, v in d.items()}
