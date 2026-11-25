"""Typed contracts exchanged between modules (extraction -> comparison -> persistence -> UI).

Keeping these in one place decouples the UI from the Power BI clients and from
the reconciliation logic. Raw extracted data (``raw_csv``) is never mutated:
any parsing produces a *new* DataFrame.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- enums
class ExtractionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    POSSIBLY_TRUNCATED = "POSSIBLY_TRUNCATED"
    SKIPPED_NON_DATA = "SKIPPED_NON_DATA"   # shapes, text boxes, images, buttons, slicers
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    UNKNOWN = "UNKNOWN"


class SourceMethod(str, Enum):
    VISUAL_EXPORT = "VISUAL_EXPORT"          # visual.exportData() — preferred evidence
    FALLBACK_QUERY = "FALLBACK_QUERY"        # Execute Queries / XMLA reconstructed data
    MOCK_FIXTURE = "MOCK_FIXTURE"            # test/demo data — never live evidence


class ExtractionMode(str, Enum):
    SUMMARIZED = "SUMMARIZED"
    UNDERLYING = "UNDERLYING"


class ContextStatus(str, Enum):
    VALIDATED = "VALIDATED"
    NOT_REQUIRED = "NOT_REQUIRED"      # e.g. migrated report is China-only by design, filters captured only
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"
    UNVERIFIED = "UNVERIFIED"


class ComparisonStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNSUPPORTED = "UNSUPPORTED"
    NOT_MAPPED = "NOT_MAPPED"
    PARTIAL = "PARTIAL"


class MismatchType(str, Enum):
    VALUE_MISMATCH = "VALUE_MISMATCH"
    NULL_MISMATCH = "NULL_MISMATCH"
    MISSING_RECORD = "MISSING_RECORD"        # in original, absent from migrated
    ADDITIONAL_RECORD = "ADDITIONAL_RECORD"  # in migrated, absent from original
    DUPLICATE_KEY = "DUPLICATE_KEY"
    MISSING_COLUMN = "MISSING_COLUMN"
    CONTEXT_VIOLATION = "CONTEXT_VIOLATION"


# --------------------------------------------------------------------------- discovery
class Workspace(BaseModel):
    id: str
    name: str
    is_read_only: bool | None = None
    is_on_dedicated_capacity: bool | None = None
    capacity_id: str | None = None


class ReportInfo(BaseModel):
    id: str
    name: str
    workspace_id: str
    dataset_id: str | None = None
    embed_url: str | None = None
    web_url: str | None = None
    report_type: str | None = None
    format: str | None = None


class PageInfo(BaseModel):
    name: str
    display_name: str
    order: int | None = None


# --------------------------------------------------------------------------- extraction
class FilterContextEvidence(BaseModel):
    status: ContextStatus = ContextStatus.UNVERIFIED
    required: bool = True
    target_table: str | None = None
    target_column: str | None = None
    value: str | None = None
    report_filters_before: list[dict[str, Any]] = Field(default_factory=list)
    report_filters_after: list[dict[str, Any]] = Field(default_factory=list)
    page_filters: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    slicer_states: list[dict[str, Any]] = Field(default_factory=list)
    bookmark_state_captured: bool = False
    action_taken: str | None = None
    messages: list[str] = Field(default_factory=list)


class VisualExtraction(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    workspace_id: str
    report_id: str
    page_name: str
    page_display_name: str
    visual_name: str
    visual_type: str
    visual_title: str | None = None
    extraction_mode: ExtractionMode = ExtractionMode.SUMMARIZED
    extracted_at: datetime = Field(default_factory=utcnow)
    status: ExtractionStatus
    completeness: Completeness = Completeness.UNKNOWN
    source_method: SourceMethod = SourceMethod.VISUAL_EXPORT
    row_count: int | None = None
    rows_requested: int | None = None
    raw_csv: str | None = None
    raw_sha256: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    truncation_info: str | None = None
    visual_filters: list[dict[str, Any]] = Field(default_factory=list)
    layout: dict[str, Any] = Field(default_factory=dict)
    screenshot_path: str | None = None
    fallback_equivalence_confirmed: bool = False

    def model_post_init(self, __context: Any) -> None:  # noqa: D401
        if self.raw_csv is not None and self.raw_sha256 is None:
            self.raw_sha256 = sha256_text(self.raw_csv)

    @property
    def has_data(self) -> bool:
        return self.status in (ExtractionStatus.SUCCESS, ExtractionStatus.POSSIBLY_TRUNCATED) and self.raw_csv is not None

    def integrity_ok(self) -> bool:
        return self.raw_csv is None or sha256_text(self.raw_csv) == self.raw_sha256

    def dataframe(self) -> pd.DataFrame:
        """Parse raw CSV into a *new* all-string DataFrame (originals untouched)."""
        if self.raw_csv is None:
            return pd.DataFrame()
        return parse_export_csv(self.raw_csv)

    @property
    def key(self) -> str:
        return f"{self.page_name}/{self.visual_name}"


class ReportExtraction(BaseModel):
    role: Literal["original", "migrated"]
    workspace_id: str
    report_id: str
    report_name: str | None = None
    dataset_id: str | None = None
    pages: list[PageInfo] = Field(default_factory=list)
    visuals: list[VisualExtraction] = Field(default_factory=list)
    context: FilterContextEvidence = Field(default_factory=FilterContextEvidence)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    is_mock: bool = False
    log: list[str] = Field(default_factory=list)
    fatal_error: str | None = None

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {s.value: 0 for s in ExtractionStatus}
        for v in self.visuals:
            out[v.status.value] += 1
        return out

    def find(self, page_name: str, visual_name: str) -> VisualExtraction | None:
        for v in self.visuals:
            if v.page_name == page_name and v.visual_name == visual_name:
                return v
        return None


# --------------------------------------------------------------------------- configuration
class ToleranceConfig(BaseModel):
    absolute: Decimal = Decimal("0")
    percentage: Decimal = Decimal("0")

    @field_validator("absolute", "percentage")
    @classmethod
    def _non_negative(cls, v: Decimal) -> Decimal:
        if v < 0:
            raise ValueError("tolerances must be >= 0")
        return v


DateGranularity = Literal["daily", "monthly", "quarterly", "yearly"]


class NormalizationRules(BaseModel):
    trim_whitespace: bool = True
    text_case: Literal["preserve", "lower", "upper"] = "preserve"
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal[",", ".", " ", ""] = ","
    strip_currency_symbols: bool = True
    percent_mode: Literal["as_number", "as_fraction"] = "as_number"
    parentheses_negative: bool = True
    null_tokens: list[str] = Field(default_factory=lambda: ["", "(Blank)", "null", "NULL", "NaN", "N/A"])
    treat_null_as_zero: bool = False
    decimal_places: int | None = None
    date_columns: dict[str, DateGranularity] = Field(default_factory=dict)
    auto_detect_dates: bool = True
    date_dayfirst: bool = False
    sort_categories: bool = True


class ColumnMapping(BaseModel):
    original: str
    migrated: str
    role: Literal["key", "value", "auto"] = "auto"
    provenance: Literal["auto", "manual"] = "manual"
    confidence: float = 1.0


class PageMapping(BaseModel):
    original_page: str
    migrated_page: str
    confidence: float = 1.0
    provenance: Literal["auto", "manual"] = "manual"
    approved: bool = False


class VisualMapping(BaseModel):
    original_page: str
    original_visual: str
    migrated_page: str
    migrated_visual: str
    confidence: float = 1.0
    provenance: Literal["auto", "manual"] = "manual"
    approved: bool = False
    signals: dict[str, float] = Field(default_factory=dict)
    explanation: str = ""
    column_mappings: list[ColumnMapping] = Field(default_factory=list)
    key_columns: list[str] = Field(default_factory=list)  # original-side names
    tolerance: ToleranceConfig | None = None
    mandatory: bool = True
    unpivot: bool | None = None          # matrix wide->long; None = auto-detect


class CountryContextConfig(BaseModel):
    original_table: str = ""
    original_column: str = ""
    original_export_column: str | None = None   # header name in exported CSV, defaults to column
    migrated_table: str = ""
    migrated_column: str = ""
    migrated_export_column: str | None = None
    value: str = "China"
    scope: Literal["report", "page"] = "report"
    apply_to_migrated: bool = False
    allow_replace_conflicting: bool = False

    @property
    def original_header(self) -> str:
        return self.original_export_column or self.original_column

    @property
    def migrated_header(self) -> str:
        return self.migrated_export_column or self.migrated_column


class ComparisonConfig(BaseModel):
    name: str = "Comparison"
    country: CountryContextConfig = Field(default_factory=CountryContextConfig)
    tolerance: ToleranceConfig = Field(default_factory=ToleranceConfig)
    normalization: NormalizationRules = Field(default_factory=NormalizationRules)
    extraction_mode: ExtractionMode = ExtractionMode.SUMMARIZED
    page_mappings: list[PageMapping] = Field(default_factory=list)
    visual_mappings: list[VisualMapping] = Field(default_factory=list)
    auto_approve_threshold: float = 0.85
    require_context_validation: bool = True


# --------------------------------------------------------------------------- results
class MismatchRecord(BaseModel):
    mismatch_type: MismatchType
    key: dict[str, Any] = Field(default_factory=dict)
    column: str | None = None
    original_value: Any = None
    migrated_value: Any = None
    absolute_difference: Decimal | None = None
    percentage_difference: Decimal | None = None
    percentage_note: str | None = None
    confirmed: bool = True
    detail: str = ""


class VisualComparisonResult(BaseModel):
    original_page: str | None = None
    original_visual: str | None = None
    original_title: str | None = None
    original_page_display: str | None = None
    migrated_page: str | None = None
    migrated_visual: str | None = None
    migrated_title: str | None = None
    migrated_page_display: str | None = None
    visual_type: str | None = None
    mandatory: bool = True
    status: ComparisonStatus
    reasons: list[str] = Field(default_factory=list)
    key_columns: list[str] = Field(default_factory=list)
    value_columns: list[str] = Field(default_factory=list)
    rows_original: int = 0
    rows_migrated: int = 0
    rows_compared: int = 0
    rows_matched: int = 0
    missing_rows: int = 0
    additional_rows: int = 0
    numeric_mismatches: int = 0
    duplicate_keys: int = 0
    matching_records: list[dict[str, Any]] = Field(default_factory=list)
    mismatches: list[MismatchRecord] = Field(default_factory=list)
    normalization_applied: list[str] = Field(default_factory=list)
    normalized_original: list[dict[str, Any]] = Field(default_factory=list)
    normalized_migrated: list[dict[str, Any]] = Field(default_factory=list)
    mapping_confidence: float | None = None
    mapping_provenance: str | None = None
    source_methods: list[str] = Field(default_factory=list)
    column_mappings_used: list[dict[str, Any]] = Field(default_factory=list)
    unmapped_columns: dict[str, list[str]] = Field(default_factory=dict)
    missing_categories: dict[str, list[str]] = Field(default_factory=dict)
    additional_categories: dict[str, list[str]] = Field(default_factory=dict)
    derived_totals: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ComparisonRunResult(BaseModel):
    run_id: int | None = None
    name: str
    overall_status: ComparisonStatus
    overall_reasons: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    is_mock: bool = False
    config: ComparisonConfig
    original: ReportExtraction
    migrated: ReportExtraction
    visual_results: list[VisualComparisonResult] = Field(default_factory=list)

    def summary(self) -> dict[str, int]:
        s = {st.value: 0 for st in ComparisonStatus}
        for r in self.visual_results:
            s[r.status.value] += 1
        return {
            "total_visuals": len(self.visual_results),
            "matched_visuals": sum(1 for r in self.visual_results if r.status != ComparisonStatus.NOT_MAPPED),
            "passed": s["PASS"],
            "failed": s["FAIL"],
            "partial": s["PARTIAL"],
            "inconclusive": s["INCONCLUSIVE"],
            "unsupported": s["UNSUPPORTED"],
            "not_mapped": s["NOT_MAPPED"],
            "rows_compared": sum(r.rows_compared for r in self.visual_results),
            "missing_rows": sum(r.missing_rows for r in self.visual_results),
            "additional_rows": sum(r.additional_rows for r in self.visual_results),
            "numeric_mismatches": sum(r.numeric_mismatches for r in self.visual_results),
        }


# --------------------------------------------------------------------------- helpers
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_export_csv(raw_csv: str) -> pd.DataFrame:
    """Parse exportData CSV into an all-string DataFrame without type coercion."""
    text = raw_csv.lstrip("﻿")
    if not text.strip():
        return pd.DataFrame()
    return pd.read_csv(
        io.StringIO(text), dtype=str, keep_default_na=False, na_filter=False, skip_blank_lines=True
    )
