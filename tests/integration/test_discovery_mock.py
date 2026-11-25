"""MOCK workspace/report discovery tests (fake HTTP transport). Not live."""
from __future__ import annotations

import pytest
import requests

from powerbi.http_client import ErrorCategory, PowerBIApiError, PowerBIHttpClient, ReadOnlyViolation
from powerbi.report_client import ReportClient
from powerbi.workspace_client import WorkspaceClient
from tests.conftest import DS_A, RPT_A, WS_A, WS_B
from tests.fixtures.fake_http import FakeResponse, FakeSession

REPORT_A = {
    "id": RPT_A, "name": "Sales Original", "datasetId": DS_A, "reportType": "PowerBIReport", "format": "PBIR",
    "webUrl": f"https://app.powerbi.com/groups/{WS_A}/reports/{RPT_A}",
    "embedUrl": f"https://app.powerbi.com/reportEmbed?reportId={RPT_A}&groupId={WS_A}",
}


def client(routes, refresh=None, retries=3):
    sleeps: list[float] = []
    http = PowerBIHttpClient("https://api.powerbi.com/v1.0/myorg", lambda: "tok", refresh_token=refresh,
                             session=FakeSession(routes), max_retries=retries, sleep=sleeps.append)
    return http, sleeps


def test_list_workspaces_paged_and_sorted():
    page1 = [{"id": f"00000000-0000-0000-0000-{i:012d}", "name": f"WS {i:04d}"} for i in range(1000)]
    page2 = [{"id": WS_B, "name": "a-first", "isReadOnly": False, "isOnDedicatedCapacity": True}]

    def groups(params=None, json=None):
        return FakeResponse(200, {"value": page1 if params["$skip"] == 0 else page2})

    http, _ = client({("GET", "/groups"): groups})
    ws = WorkspaceClient(http).list_workspaces()
    assert len(ws) == 1001 and ws[0].name == "a-first" and ws[0].is_on_dedicated_capacity


def test_list_reports_and_pages():
    routes = {
        ("GET", f"/groups/{WS_A}/reports"): FakeResponse(200, {"value": [
            REPORT_A, {"id": "dddddddd-dddd-dddd-dddd-dddddddddddd", "name": "Paginated", "reportType": "PaginatedReport"}]}),
        ("GET", f"/groups/{WS_A}/reports/{RPT_A}/pages"): FakeResponse(200, {"value": [
            {"name": "ReportSection2", "displayName": "Details", "order": "1"},
            {"name": "ReportSection1", "displayName": "Overview", "order": 0}]}),
    }
    http, _ = client(routes)
    rc = ReportClient(http)
    reports = rc.list_reports(WS_A)
    assert [r.name for r in reports] == ["Sales Original"]
    assert reports[0].dataset_id == DS_A  # report and dataset ids kept separate
    pages = rc.list_pages(WS_A, RPT_A)
    assert [p.display_name for p in pages] == ["Overview", "Details"]


def test_validate_access_success_and_errors():
    routes = {
        ("GET", f"/groups/{WS_A}/reports/{RPT_A}"): FakeResponse(200, REPORT_A),
        ("GET", f"/groups/{WS_A}/reports/{RPT_A}/pages"): FakeResponse(200, {"value": [{"name": "P1", "displayName": "P1", "order": 0}]}),
    }
    http, _ = client(routes)
    v = ReportClient(http).validate_access(WS_A, RPT_A)
    assert v.ok and v.report.name == "Sales Original"

    http, _ = client({("GET", f"/groups/{WS_A}/reports/{RPT_A}"): FakeResponse(403, {"error": {"code": "Unauthorized"}})})
    v = ReportClient(http).validate_access(WS_A, RPT_A)
    assert not v.ok and "Access denied" in v.problems[0]

    v = ReportClient(http).validate_access("not-a-guid", RPT_A)
    assert not v.ok and "GUID" in v.problems[0]

    http, _ = client({})  # deleted / invalid report -> 404
    v = ReportClient(http).validate_access(WS_A, RPT_A)
    assert not v.ok and "Not found" in v.problems[0]


def test_throttling_honours_retry_after():
    routes = {("GET", "/groups"): [FakeResponse(429, {}, {"Retry-After": "7"}), FakeResponse(200, {"value": []})]}
    http, sleeps = client(routes)
    assert http.get("/groups") == {"value": []}
    assert sleeps == [7.0]


def test_throttling_exhausted_raises():
    routes = {("GET", "/groups"): [FakeResponse(429, {}, {"Retry-After": "1"})]}
    http, sleeps = client(routes, retries=2)
    with pytest.raises(PowerBIApiError) as e:
        http.get("/groups")
    assert e.value.category == ErrorCategory.THROTTLED and len(sleeps) == 2


def test_network_failure_retried_then_raised():
    routes = {("GET", "/groups"): [requests.ConnectionError("down")]}
    http, sleeps = client(routes, retries=1)
    with pytest.raises(PowerBIApiError) as e:
        http.get("/groups")
    assert e.value.category == ErrorCategory.NETWORK and len(sleeps) == 1


def test_expired_token_refreshed_once():
    refreshed: list[int] = []
    routes = {("GET", "/groups"): [FakeResponse(401, {"error": {"code": "TokenExpired"}}), FakeResponse(200, {"value": []})]}
    http, _ = client(routes, refresh=lambda: refreshed.append(1) or "new")
    http.get("/groups")
    assert refreshed == [1]

    routes = {("GET", "/groups"): [FakeResponse(401, {"error": {"code": "TokenExpired"}})]}
    http, _ = client(routes, refresh=lambda: "new")
    with pytest.raises(PowerBIApiError) as e:
        http.get("/groups")
    assert e.value.category == ErrorCategory.AUTH_EXPIRED


def test_read_only_enforced():
    http, _ = client({})
    with pytest.raises(ReadOnlyViolation):
        http.post_readonly(f"/groups/{WS_A}/reports/{RPT_A}/Clone", {})
    with pytest.raises(ReadOnlyViolation):
        http._request("DELETE", f"/groups/{WS_A}/reports/{RPT_A}")
    with pytest.raises(ReadOnlyViolation):
        http._request("PATCH", "/groups")


def test_error_detail_sanitized():
    routes = {("GET", "/groups"): FakeResponse(400, {"error": {"code": "Bad", "message": "token=eyJabcdefghij.eyJabcdefghij.sigsigsigsig"}})}
    http, _ = client(routes)
    with pytest.raises(PowerBIApiError) as e:
        http.get("/groups")
    assert "eyJabcdefghij" not in e.value.detail
