import pandas as pd

from comparison.column_mapper import apply_column_mappings, suggest_column_mappings
from comparison.visual_matcher import MatchSettings, suggest_visual_mappings, text_similarity, type_similarity
from core.contracts import (
    ColumnMapping,
    ExtractionStatus,
    PageInfo,
    ReportExtraction,
    VisualExtraction,
    VisualMapping,
)


def V(page, name, vtype, title, csv=None, status=ExtractionStatus.SUCCESS):
    return VisualExtraction(workspace_id="w", report_id="r", page_name=page, page_display_name=page, visual_name=name,
                            visual_type=vtype, visual_title=title, status=status, raw_csv=csv)


def R(role, visuals, pages=("P1",)):
    return ReportExtraction(role=role, workspace_id="w", report_id="r", pages=[PageInfo(name=p, display_name=p) for p in pages],
                            visuals=visuals)


def test_column_mapping_synonyms_and_values():
    o = pd.DataFrame({"MonthName": ["Jan", "Feb"], "SalesAmount": ["1", "2"]})
    m = pd.DataFrame({"Period": ["Jan", "Feb"], "Revenue": ["1", "2"]})
    maps = {c.original: c.migrated for c in suggest_column_mappings(o, m)}
    assert maps == {"MonthName": "Period", "SalesAmount": "Revenue"}


def test_apply_column_mappings_reports_unmapped():
    o = pd.DataFrame({"A": [1], "B": [2], "X": [0]})
    m = pd.DataFrame({"a2": [1], "b2": [2], "Y": [0]})
    od, md, un = apply_column_mappings(o, m, [ColumnMapping(original="A", migrated="a2"), ColumnMapping(original="B", migrated="b2")])
    assert list(md.columns) == ["A", "B"] and un == {"original": ["X"], "migrated": ["Y"]}


def test_similarity_helpers():
    assert text_similarity("Total Sales", "total sales") == 1.0
    assert text_similarity(None, "x") is None
    assert type_similarity("pieChart", "donutChart") == 0.8
    assert type_similarity("pieChart", "tableEx") == 0.0


CSV_A = "Category,Sales\r\nA,1\r\nB,2\r\nC,3\r\n"
CSV_B = "Category,Revenue\r\nA,1\r\nB,2\r\nC,3\r\n"


def test_high_confidence_auto_approved():
    o = R("original", [V("P1", "v1", "clusteredBarChart", "Sales by Category", CSV_A)])
    m = R("migrated", [V("P1", "w1", "clusteredBarChart", "Sales by Category", CSV_B)])
    maps = suggest_visual_mappings(o, m)
    assert len(maps) == 1 and maps[0].approved and maps[0].confidence >= 0.85
    assert "title" in maps[0].signals


def test_ambiguous_not_auto_approved():
    o = R("original", [V("P1", "v1", "card", "Total", "Total\r\n5\r\n")])
    m = R("migrated", [V("P1", "w1", "card", "Total", "Total\r\n5\r\n"), V("P1", "w2", "card", "Total", "Total\r\n5\r\n")])
    maps = suggest_visual_mappings(o, m)
    assert len(maps) == 1 and not maps[0].approved and "AMBIGUOUS" in maps[0].explanation


def test_low_confidence_not_suggested_and_manual_wins():
    o = R("original", [V("P1", "v1", "card", "Total Sales", "Total\r\n5\r\n")])
    m = R("migrated", [V("P9", "w1", "tableEx", "Customer list", "Name,City\r\nX,Y\r\nZ,Q\r\n")], pages=("P9",))
    assert suggest_visual_mappings(o, m, MatchSettings(min_suggest=0.5)) == []
    manual = [VisualMapping(original_page="P1", original_visual="v1", migrated_page="P9", migrated_visual="w1")]
    maps = suggest_visual_mappings(o, m, manual=manual)
    assert len(maps) == 1 and maps[0].approved and maps[0].provenance == "manual"


def test_failed_visuals_still_matchable_by_title():
    o = R("original", [V("P1", "v1", "lineChart", "Trend", None, ExtractionStatus.FAILED)])
    m = R("migrated", [V("P1", "w1", "lineChart", "Trend", None, ExtractionStatus.FAILED)])
    maps = suggest_visual_mappings(o, m)
    assert len(maps) == 1 and "not available" in maps[0].explanation
