from fastapi.testclient import TestClient

import api.main as api
from services.comparison_service import run_demo


def test_api_read_only_endpoints(repo):
    api._repo = repo
    run = run_demo(repo, approve_all_suggestions=True)
    c = TestClient(api.app)
    assert c.get("/health").json()["read_only"] is True
    assert c.get("/runs").json()[0]["id"] == run.run_id
    body = c.get(f"/runs/{run.run_id}").json()
    assert body["overall_status"] == "FAIL" and body["is_mock"] is True
    assert c.get(f"/runs/{run.run_id}/export/xlsx").status_code == 200
    assert c.get(f"/runs/{run.run_id}/export/pdf").status_code == 400
    assert c.get("/runs/999").status_code == 404
    assert c.post("/runs").status_code == 405  # no write endpoints
    api._repo = None
