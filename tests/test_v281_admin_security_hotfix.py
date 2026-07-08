import http.client
import re
import socket
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


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _post(port: int, path: str, payload: str, headers: dict[str, str] | None = None):
    merged = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        merged.update(headers)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", path, payload, merged)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    status = resp.status
    conn.close()
    return status, body


def test_v281_version():
    assert __version__ == "3.1.25"


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


def test_v304_admin_post_requires_same_origin_header_even_with_valid_csrf():
    port = _free_port()
    panel = AdminPanelServer(port=port)
    server = ThreadingHTTPServer(("127.0.0.1", port), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = f"csrf_token={panel.csrf_token}"
        status, body = _post(port, "/stage", payload)
        assert status == 403
        assert "origin" in body.lower()
    finally:
        server.shutdown()
        server.server_close()


def test_v304_admin_post_rejects_bad_origin_even_with_valid_csrf():
    port = _free_port()
    panel = AdminPanelServer(port=port)
    server = ThreadingHTTPServer(("127.0.0.1", port), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = f"csrf_token={panel.csrf_token}"
        status, body = _post(port, "/stage", payload, {"Origin": "http://evil.example"})
        assert status == 403
        assert "origin" in body.lower()
    finally:
        server.shutdown()
        server.server_close()


def test_v304_admin_post_accepts_valid_origin_and_csrf():
    port = _free_port()
    panel = AdminPanelServer(port=port)
    server = ThreadingHTTPServer(("127.0.0.1", port), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = f"csrf_token={panel.csrf_token}"
        expected = f"http://127.0.0.1:{port}"
        status, _ = _post(port, "/stage", payload, {"Origin": expected})
        assert status == 303
    finally:
        server.shutdown()
        server.server_close()


def test_v304_admin_post_accepts_valid_referer_and_csrf():
    port = _free_port()
    panel = AdminPanelServer(port=port)
    server = ThreadingHTTPServer(("127.0.0.1", port), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        payload = f"csrf_token={panel.csrf_token}"
        expected = f"http://127.0.0.1:{port}/dashboard"
        status, _ = _post(port, "/stage", payload, {"Referer": expected})
        assert status == 303
    finally:
        server.shutdown()
        server.server_close()


def test_v304_admin_post_requires_csrf_after_origin_passes():
    port = _free_port()
    panel = AdminPanelServer(port=port)
    server = ThreadingHTTPServer(("127.0.0.1", port), panel.make_handler())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_port
        expected = f"http://127.0.0.1:{port}"
        status, body = _post(port, "/promote", "", {"Origin": expected})
        assert status == 403
        assert "csrf" in body.lower()
    finally:
        server.shutdown()
        server.server_close()
