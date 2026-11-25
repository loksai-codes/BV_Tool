"""SQLAlchemy 2.x ORM models. Portable to PostgreSQL (generic types, JSON columns).

No tokens/secrets are ever stored. User references hold only a SHA-256 hash of
the account name plus an optional display label.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from core.contracts import utcnow


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    description: Mapped[str] = mapped_column(String(200))


class UserRef(Base):
    __tablename__ = "user_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_label: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonSession(Base):
    __tablename__ = "comparison_sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    user_ref_id: Mapped[int | None] = mapped_column(ForeignKey("user_refs.id"))
    overall_status: Mapped[str] = mapped_column(String(20), index=True)
    overall_reasons: Mapped[list] = mapped_column(JSON, default=list)
    config_json: Mapped[dict] = mapped_column(JSON)
    summary_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspaces: Mapped[list[WorkspaceRef]] = relationship(back_populates="session", cascade="all, delete-orphan")
    reports: Mapped[list[ReportSelection]] = relationship(back_populates="session", cascade="all, delete-orphan")
    page_mappings: Mapped[list[PageMappingRow]] = relationship(cascade="all, delete-orphan")
    visual_mappings: Mapped[list[VisualMappingRow]] = relationship(cascade="all, delete-orphan")
    filter_configs: Mapped[list[FilterConfiguration]] = relationship(cascade="all, delete-orphan")
    extraction_runs: Mapped[list[ExtractionRun]] = relationship(back_populates="session", cascade="all, delete-orphan")
    results: Mapped[list[ReconciliationResultRow]] = relationship(back_populates="session", cascade="all, delete-orphan")


class WorkspaceRef(Base):
    __tablename__ = "workspace_refs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    workspace_id: Mapped[str] = mapped_column(String(36))
    workspace_name: Mapped[str | None] = mapped_column(String(256))
    session: Mapped[ComparisonSession] = relationship(back_populates="workspaces")


class ReportSelection(Base):
    __tablename__ = "report_selections"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    workspace_id: Mapped[str] = mapped_column(String(36))
    report_id: Mapped[str] = mapped_column(String(36), index=True)
    report_name: Mapped[str | None] = mapped_column(String(256))
    dataset_id: Mapped[str | None] = mapped_column(String(36))
    session: Mapped[ComparisonSession] = relationship(back_populates="reports")


class PageMappingRow(Base):
    __tablename__ = "page_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    original_page: Mapped[str] = mapped_column(String(256))
    migrated_page: Mapped[str] = mapped_column(String(256))
    confidence: Mapped[float] = mapped_column(Float)
    provenance: Mapped[str] = mapped_column(String(10))
    approved: Mapped[bool] = mapped_column(Boolean)


class VisualMappingRow(Base):
    __tablename__ = "visual_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    original_page: Mapped[str] = mapped_column(String(256))
    original_visual: Mapped[str] = mapped_column(String(256))
    migrated_page: Mapped[str] = mapped_column(String(256))
    migrated_visual: Mapped[str] = mapped_column(String(256))
    confidence: Mapped[float] = mapped_column(Float)
    provenance: Mapped[str] = mapped_column(String(10))
    approved: Mapped[bool] = mapped_column(Boolean)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=True)
    signals_json: Mapped[dict] = mapped_column(JSON, default=dict)
    key_columns: Mapped[list] = mapped_column(JSON, default=list)
    columns: Mapped[list[ColumnMappingRow]] = relationship(cascade="all, delete-orphan")


class ColumnMappingRow(Base):
    __tablename__ = "column_mappings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visual_mapping_id: Mapped[int] = mapped_column(ForeignKey("visual_mappings.id", ondelete="CASCADE"), index=True)
    original: Mapped[str] = mapped_column(String(256))
    migrated: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(10))
    provenance: Mapped[str] = mapped_column(String(10))


class FilterConfiguration(Base):
    __tablename__ = "filter_configurations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    config_json: Mapped[dict] = mapped_column(JSON)


class MappingProfile(Base):
    """Approved mappings saved for reuse between the same pair of reports."""

    __tablename__ = "mapping_profiles"
    __table_args__ = (UniqueConstraint("original_report_id", "migrated_report_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    original_report_id: Mapped[str] = mapped_column(String(64), index=True)
    migrated_report_id: Mapped[str] = mapped_column(String(64), index=True)
    mappings_json: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    workspace_id: Mapped[str] = mapped_column(String(64))
    report_id: Mapped[str] = mapped_column(String(64))
    report_name: Mapped[str | None] = mapped_column(String(256))
    dataset_id: Mapped[str | None] = mapped_column(String(64))
    pages_json: Mapped[list] = mapped_column(JSON, default=list)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    counts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    log_json: Mapped[list] = mapped_column(JSON, default=list)
    fatal_error: Mapped[str | None] = mapped_column(Text)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    session: Mapped[ComparisonSession] = relationship(back_populates="extraction_runs")
    visuals: Mapped[list[ExtractedVisual]] = relationship(back_populates="run", cascade="all, delete-orphan")


class ExtractedVisual(Base):
    __tablename__ = "extracted_visuals"
    __table_args__ = (Index("ix_extracted_visual_identity", "extraction_run_id", "page_name", "visual_name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extraction_run_id: Mapped[int] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"))
    page_name: Mapped[str] = mapped_column(String(256))
    page_display_name: Mapped[str] = mapped_column(String(256))
    visual_name: Mapped[str] = mapped_column(String(256))
    visual_type: Mapped[str] = mapped_column(String(100))
    visual_title: Mapped[str | None] = mapped_column(String(512))
    extraction_mode: Mapped[str] = mapped_column(String(20))
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), index=True)
    completeness: Mapped[str] = mapped_column(String(20))
    source_method: Mapped[str] = mapped_column(String(20))
    row_count: Mapped[int | None] = mapped_column(Integer)
    rows_requested: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    truncation_info: Mapped[str | None] = mapped_column(Text)
    filters_json: Mapped[list] = mapped_column(JSON, default=list)
    layout_json: Mapped[dict] = mapped_column(JSON, default=dict)
    screenshot_path: Mapped[str | None] = mapped_column(String(512))
    fallback_equivalence_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    run: Mapped[ExtractionRun] = relationship(back_populates="visuals")
    data: Mapped[ExtractedVisualData | None] = relationship(back_populates="visual", cascade="all, delete-orphan", uselist=False)


class ExtractedVisualData(Base):
    """Raw, unmodified exported CSV + SHA-256 for integrity verification."""

    __tablename__ = "extracted_visual_data"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extracted_visual_id: Mapped[int] = mapped_column(ForeignKey("extracted_visuals.id", ondelete="CASCADE"), unique=True)
    raw_csv: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    visual: Mapped[ExtractedVisual] = relationship(back_populates="data")


class ReconciliationResultRow(Base):
    __tablename__ = "reconciliation_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("comparison_sessions.id", ondelete="CASCADE"), index=True)
    original_page: Mapped[str | None] = mapped_column(String(256))
    original_visual: Mapped[str | None] = mapped_column(String(256))
    migrated_page: Mapped[str | None] = mapped_column(String(256))
    migrated_visual: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(20), index=True)
    reasons_json: Mapped[list] = mapped_column(JSON, default=list)
    rows_compared: Mapped[int] = mapped_column(Integer, default=0)
    missing_rows: Mapped[int] = mapped_column(Integer, default=0)
    additional_rows: Mapped[int] = mapped_column(Integer, default=0)
    numeric_mismatches: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON)
    session: Mapped[ComparisonSession] = relationship(back_populates="results")
    mismatches: Mapped[list[MismatchRow]] = relationship(cascade="all, delete-orphan")


class MismatchRow(Base):
    __tablename__ = "mismatch_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reconciliation_result_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_results.id", ondelete="CASCADE"), index=True)
    mismatch_type: Mapped[str] = mapped_column(String(30), index=True)
    key_json: Mapped[dict] = mapped_column(JSON, default=dict)
    column: Mapped[str | None] = mapped_column(String(256))
    original_value: Mapped[str | None] = mapped_column(Text)
    migrated_value: Mapped[str | None] = mapped_column(Text)
    absolute_difference: Mapped[str | None] = mapped_column(String(64))   # Decimal as text (exact)
    percentage_difference: Mapped[str | None] = mapped_column(String(64))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str | None] = mapped_column(Text)


class Screenshot(Base):
    __tablename__ = "screenshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extraction_run_id: Mapped[int | None] = mapped_column(ForeignKey("extraction_runs.id", ondelete="CASCADE"), index=True)
    page_name: Mapped[str | None] = mapped_column(String(256))
    visual_name: Mapped[str | None] = mapped_column(String(256))
    path: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_ref_id: Mapped[int | None] = mapped_column(ForeignKey("user_refs.id"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    detail: Mapped[str | None] = mapped_column(Text)
