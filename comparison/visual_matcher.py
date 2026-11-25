"""Automatic page/visual matching with explainable confidence scores.

No single attribute is trusted: title, type, page, column structure, data shape,
category labels and series count are combined with configurable weights.
Signals that cannot be computed (e.g. no data) are excluded and the remaining
weights renormalised. Ambiguous or low-confidence matches are never auto-approved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from comparison.column_mapper import name_similarity
from comparison.data_normalizer import DataNormalizer
from core.contracts import ExtractionStatus, PageMapping, ReportExtraction, VisualExtraction, VisualMapping

TYPE_FAMILIES = [
    {"clusteredBarChart", "clusteredColumnChart", "stackedBarChart", "stackedColumnChart",
     "hundredPercentStackedBarChart", "hundredPercentStackedColumnChart", "ribbonChart"},
    {"lineChart", "areaChart", "stackedAreaChart"},
    {"lineClusteredColumnComboChart", "lineStackedColumnComboChart"},
    {"pieChart", "donutChart", "treemap"},
    {"card", "cardVisual", "multiRowCard", "kpi", "gauge"},
    {"tableEx", "pivotTable"},
    {"map", "filledMap"},
]


@dataclass
class MatchWeights:
    title: float = 0.30
    type: float = 0.15
    page: float = 0.10
    columns: float = 0.15
    shape: float = 0.05
    categories: float = 0.20
    series: float = 0.05


@dataclass
class MatchSettings:
    weights: MatchWeights = field(default_factory=MatchWeights)
    auto_approve_threshold: float = 0.85
    min_suggest: float = 0.40
    ambiguity_margin: float = 0.05


def _norm_title(t: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()


def text_similarity(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    na, nb = _norm_title(a), _norm_title(b)
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if ta | tb else 0
    return max(seq, jac)


def type_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    for fam in TYPE_FAMILIES:
        if a in fam and b in fam:
            return 0.8
    return 0.0


@dataclass
class _Profile:
    v: VisualExtraction
    page_display: str
    columns: list[str]
    numeric: list[str]
    categories: set[str]
    rows: int | None


def _profile(v: VisualExtraction, page_display: str, n: DataNormalizer) -> _Profile:
    cols, num, cats, rows = [], [], set(), None
    if v.has_data:
        df = v.dataframe()
        cols = list(df.columns)
        num = n.infer_numeric_columns(df)
        rows = len(df)
        text_cols = [c for c in cols if c not in num]
        if text_cols:
            cats = {_canon_category(x, n) for x in df[text_cols[0]].tolist()} - {None}
    return _Profile(v, page_display, cols, num, cats, rows)


def _canon_category(x, n: DataNormalizer) -> str | None:
    """Canonical label for category overlap: dates rendered at month level, text normalized."""
    p = n.parse_date(x)
    if p is not None:
        return p.render("monthly")
    return n.normalize_text(x)


def score_pair(a: _Profile, b: _Profile, s: MatchSettings, page_bonus: float | None = None) -> tuple[float, dict[str, float], str]:
    w = s.weights
    signals: dict[str, float] = {}
    t = text_similarity(a.v.visual_title, b.v.visual_title)
    if t is not None:
        signals["title"] = t
    signals["type"] = type_similarity(a.v.visual_type, b.v.visual_type)
    signals["page"] = page_bonus if page_bonus is not None else (text_similarity(a.page_display, b.page_display) or 0.0)
    if a.columns and b.columns:
        if len(a.columns) == len(b.columns):
            name_scores = [max(name_similarity(x, y) for y in b.columns) for x in a.columns]
            signals["columns"] = 0.5 + 0.5 * (sum(name_scores) / len(name_scores))
        else:
            signals["columns"] = min(len(a.columns), len(b.columns)) / max(len(a.columns), len(b.columns)) * 0.6
        signals["series"] = 1.0 if len(a.numeric) == len(b.numeric) else (
            min(len(a.numeric), len(b.numeric)) / max(len(a.numeric), len(b.numeric), 1))
    if a.rows is not None and b.rows is not None:
        signals["shape"] = 1.0 if a.rows == b.rows else min(a.rows, b.rows) / max(a.rows, b.rows, 1)
    if a.categories and b.categories:
        signals["categories"] = len(a.categories & b.categories) / len(a.categories | b.categories)
    total_w = sum(getattr(w, k) for k in signals)
    score = sum(getattr(w, k) * v for k, v in signals.items()) / total_w if total_w else 0.0
    missing = [k for k in ("title", "columns", "shape", "categories", "series") if k not in signals]
    expl = ", ".join(f"{k}={v:.2f}" for k, v in signals.items())
    if missing:
        expl += f" (not available: {', '.join(missing)}; weights renormalised)"
    return round(score, 4), {k: round(v, 4) for k, v in signals.items()}, expl


def _candidates(ext: ReportExtraction) -> list[VisualExtraction]:
    return [v for v in ext.visuals if v.status != ExtractionStatus.SKIPPED_NON_DATA and v.visual_name != "__page_enumeration__"]


def suggest_visual_mappings(
    original: ReportExtraction,
    migrated: ReportExtraction,
    settings: MatchSettings | None = None,
    manual: list[VisualMapping] | None = None,
    page_mappings: list[PageMapping] | None = None,
) -> list[VisualMapping]:
    s = settings or MatchSettings()
    n = DataNormalizer()
    manual = manual or []
    approved_pages = {(p.original_page, p.migrated_page) for p in (page_mappings or []) if p.approved}
    o_pages = {p.name: p.display_name for p in original.pages}
    m_pages = {p.name: p.display_name for p in migrated.pages}
    o_prof = [_profile(v, o_pages.get(v.page_name, v.page_display_name), n) for v in _candidates(original)]
    m_prof = [_profile(v, m_pages.get(v.page_name, v.page_display_name), n) for v in _candidates(migrated)]

    out: list[VisualMapping] = []
    used_o = {(m.original_page, m.original_visual) for m in manual}
    used_m = {(m.migrated_page, m.migrated_visual) for m in manual}
    for m in manual:
        out.append(m.model_copy(update={"provenance": "manual", "approved": True}))

    pairs: list[tuple[float, int, int, dict[str, float], str]] = []
    matrix: dict[tuple[int, int], float] = {}
    for i, a in enumerate(o_prof):
        for j, b in enumerate(m_prof):
            bonus = 1.0 if (a.v.page_name, b.v.page_name) in approved_pages else None
            sc, sig, expl = score_pair(a, b, s, bonus)
            matrix[(i, j)] = sc
            pairs.append((sc, i, j, sig, expl))
    pairs.sort(key=lambda p: -p[0])
    taken_o, taken_m = set(), set()
    for sc, i, j, sig, expl in pairs:
        a, b = o_prof[i], m_prof[j]
        ka, kb = (a.v.page_name, a.v.visual_name), (b.v.page_name, b.v.visual_name)
        if i in taken_o or j in taken_m or ka in used_o or kb in used_m or sc < s.min_suggest:
            continue
        alt_o = max((matrix[(i, jj)] for jj in range(len(m_prof)) if jj != j and jj not in taken_m), default=0.0)
        alt_m = max((matrix[(ii, j)] for ii in range(len(o_prof)) if ii != i and ii not in taken_o), default=0.0)
        ambiguous = max(alt_o, alt_m) >= sc - s.ambiguity_margin
        taken_o.add(i)
        taken_m.add(j)
        approve = sc >= s.auto_approve_threshold and not ambiguous
        note = "auto-approved (high confidence, unambiguous)" if approve else (
            "AMBIGUOUS: a competing candidate scores within margin; review required" if ambiguous
            else "below auto-approve threshold; review required")
        out.append(VisualMapping(
            original_page=a.v.page_name, original_visual=a.v.visual_name,
            migrated_page=b.v.page_name, migrated_visual=b.v.visual_name,
            confidence=sc, provenance="auto", approved=approve, signals=sig, explanation=f"{note}. Signals: {expl}",
        ))
    return out


def suggest_page_mappings(original: ReportExtraction, migrated: ReportExtraction,
                          visual_mappings: list[VisualMapping], threshold: float = 0.6) -> list[PageMapping]:
    out: list[PageMapping] = []
    used = set()
    for op in original.pages:
        best, best_score = None, 0.0
        for mp in migrated.pages:
            if mp.name in used:
                continue
            name = text_similarity(op.display_name, mp.display_name) or 0.0
            o_count = sum(1 for v in visual_mappings if v.original_page == op.name)
            shared = sum(1 for v in visual_mappings if v.original_page == op.name and v.migrated_page == mp.name)
            vis = shared / o_count if o_count else 0.0
            sc = round(0.4 * name + 0.6 * vis, 4)
            if sc > best_score:
                best, best_score = mp, sc
        if best is not None and best_score >= 0.3:
            used.add(best.name)
            out.append(PageMapping(original_page=op.name, migrated_page=best.name, confidence=best_score,
                                   provenance="auto", approved=best_score >= threshold))
    return out
