import os
import time

from PIL import Image

from config.settings import AuthMode
from core.contracts import ReportInfo
from powerbi.embed_manager import EmbedManager
from powerbi.http_client import PowerBIHttpClient
from reporting.screenshot_capture import cleanup_old, crop_visual, ocr_text, sha256_file
from tests.conftest import DS_A, RPT_A, WS_A
from tests.fixtures.fake_http import FakeResponse, FakeSession

REPORT = ReportInfo(id=RPT_A, name="r", workspace_id=WS_A, dataset_id=DS_A, embed_url="https://app.powerbi.com/reportEmbed?x")


def test_user_owns_data_uses_aad_token():
    em = EmbedManager(None, AuthMode.INTERACTIVE, lambda: "user-token")
    cfg = em.build(REPORT)
    assert cfg.token_type == "Aad" and cfg.to_js(1000)["accessToken"] == "user-token"
    assert "user-token" not in repr(cfg)


def test_service_principal_view_only_embed_token_no_identities():
    s = FakeSession({("POST", "/GenerateToken"): FakeResponse(200, {"token": "embed", "tokenId": "t", "expiration": "x"})})
    http = PowerBIHttpClient("https://api.powerbi.com/v1.0/myorg", lambda: "sp", session=s, sleep=lambda x: None)
    cfg = EmbedManager(http, AuthMode.SERVICE_PRINCIPAL, lambda: "sp").build(REPORT)
    body = s.calls[0]["json"]
    assert cfg.token_type == "Embed"
    assert body["reports"] == [{"id": RPT_A, "allowEdit": False}]
    assert body["datasets"] == [{"id": DS_A, "xmlaPermissions": "Off"}]
    assert "identities" not in body and "targetWorkspaces" not in body


def test_crop_and_cleanup(tmp_path):
    page = tmp_path / "page.png"
    Image.new("RGB", (1280, 720), "white").save(page)
    out = crop_visual(page, {"x": 100, "y": 50, "width": 200, "height": 100}, (1280, 720), tmp_path / "v.png")
    with Image.open(out) as im:
        assert im.size == (200, 100)
    assert crop_visual(page, {}, None, tmp_path / "n.png") is None
    assert len(sha256_file(page)) == 64
    assert ocr_text(out) is None or isinstance(ocr_text(out), str)
    old = time.time() - 10 * 86400
    os.utime(page, (old, old))
    assert cleanup_old(tmp_path, 5) == 1 and not page.exists()
