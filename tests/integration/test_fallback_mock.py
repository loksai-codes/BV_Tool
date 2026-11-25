"""MOCK Execute Queries fallback tests (fake HTTP). Not live."""
from __future__ import annotations

import pytest

from core.contracts import ExtractionStatus, SourceMethod, VisualExtraction
from powerbi.dax_query_fallback import ExecuteQueriesFallback, FallbackQuerySpec
from powerbi.http_client import PowerBIHttpClient
from powerbi.xmla_client import build_connection_string, is_available
from tests.conftest import DS_A, WS_A
from tests.fixtures.fake_http import FakeResponse, FakeSession

PATH = f"/groups/{WS_A}/datasets/{DS_A}/executeQueries"
TEMPLATE = VisualExtraction(workspace_id=WS_A, report_id="r", page_name="P", page_display_name="P", visual_name="v",
                            visual_type="bulletChartXYZ", visual_title="Target Bullet", status=ExtractionStatus.UNSUPPORTED)


def fb(route):
    session = FakeSession({("POST", PATH): route})
    return ExecuteQueriesFallback(PowerBIHttpClient("https://api.powerbi.com/v1.0/myorg", lambda: "t", session=session,
                                                    sleep=lambda s: None)), session


def test_builds_summarize_query_with_escaping():
    s = FallbackQuerySpec(WS_A, DS_A, group_by=[("Product's", "Category")], measures=[("Sales", "Total Sales]")],
                          country_filter=("Geography", "CountryName", 'Chi"na'))
    q = s.query()
    assert "'Product''s'[Category]" in q and 'TREATAS({"Chi""na"}' in q and "[Total Sales]]]" in q
    assert q.startswith("EVALUATE")


def test_rejects_non_query_dax():
    with pytest.raises(ValueError):
        FallbackQuerySpec(WS_A, DS_A, dax_query="DROP TABLE x").query()


def test_success_labelled_fallback_no_impersonation():
    body = {"results": [{"tables": [{"rows": [{"Product[Category]": "A", "[Sales]": 10}, {"Product[Category]": "B", "[Sales]": None}]}]}]}
    f, session = fb(FakeResponse(200, body))
    v = f.extract(FallbackQuerySpec(WS_A, DS_A, dax_query="EVALUATE VALUES('T')"), TEMPLATE)
    assert v.status == ExtractionStatus.SUCCESS and v.source_method == SourceMethod.FALLBACK_QUERY
    assert v.raw_csv.splitlines()[0] == "Category,Sales" and v.row_count == 2
    assert "FALLBACK" in v.truncation_info
    assert "impersonatedUserName" not in session.calls[0]["json"]
    assert not v.fallback_equivalence_confirmed


def test_query_error_and_http_error():
    f, _ = fb(FakeResponse(200, {"results": [{"error": {"code": "DatasetExecuteQueriesError", "message": "bad"}}]}))
    v = f.extract(FallbackQuerySpec(WS_A, DS_A, dax_query="EVALUATE x"), TEMPLATE)
    assert v.status == ExtractionStatus.FAILED and v.error_code == "DatasetExecuteQueriesError"
    f, _ = fb(FakeResponse(403, {"error": {"code": "PowerBINotAuthorizedException"}}))
    v = f.extract(FallbackQuerySpec(WS_A, DS_A, dax_query="EVALUATE x"), TEMPLATE)
    assert v.status == ExtractionStatus.FAILED and "Access denied" in v.error_message


def test_row_limit_marks_truncated():
    rows = [{"T[a]": i} for i in range(100_000)]
    f, _ = fb(FakeResponse(200, {"results": [{"tables": [{"rows": rows}]}]}))
    v = f.extract(FallbackQuerySpec(WS_A, DS_A, dax_query="EVALUATE x"), TEMPLATE)
    assert v.status == ExtractionStatus.POSSIBLY_TRUNCATED


def test_xmla_connection_string():
    cs = build_connection_string("Sales Workspace", "Sales Model")
    assert "powerbi://api.powerbi.com/v1.0/myorg/Sales%20Workspace" in cs and "Initial Catalog=Sales Model" in cs
    assert isinstance(is_available(), bool)
