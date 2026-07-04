import http.client
import re
import threading
from http.server import ThreadingHTTPServer

from staqtapp_tds import __version__
from staqtapp_tds.admin.panel import AdminPanelServer, render_dashboard_html


def _asset(path: str) -> str:
    panel = AdminPanelServer()
    asset = panel._static_asset(path)
    assert asset is not None, path
    data, _ = asset
    return data.decode("utf-8")


def test_v281_version():
    assert __version__ == "2.9.4"


def test_v281_dashboard_embeds_csrf_token_meta():
    html = render_dashboard_html(version="2.8.1", csrf_token="abc123")
    assert 'name="tds-csrf-token"' in html
    assert 'content="abc123"' in html


def test_v281_dashboard_js_avoids_innerhtml_for_dynamic_payloads():
    js = _asset("/static/js/dashboard.js")
    assert ".innerHTML" not in js
    assert "replaceChildren" in js
    assert "textContent" in js
    assert "appendPairRow" in js


def test_v281_i18n_settings_are_sanitized_and_fallback_visible():
    js = _asset("/static/js/i18n.js")
    assert "sanitizeSettings" in js
    assert "allowedRefresh" in js
    assert "i18nStatus" in js
    assert "packLoadErrors" in js
    assert "return ms > 0 ? ms : 0" in js


def test_v281_admin_post_requires_csrf_token():
    panel = AdminPanelServer(port=0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("POST", "/promote", "", {"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        assert resp.status == 403
        assert "csrf" in body.lower()
        conn.close()

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        payload = f"csrf_token={panel.csrf_token}"
        conn.request("POST", "/stage", payload, {"Content-Type": "application/x-www-form-urlencoded"})
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 303
        conn.close()
    finally:
        server.shutdown()
        server.server_close()
