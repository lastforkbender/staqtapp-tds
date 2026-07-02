from __future__ import annotations

import html
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote

from staqtapp_tds import __version__
from staqtapp_tds.admin.control import AdminControl

PANEL_REFRESH_SECONDS = 2.0


def _resource_text(relative: str) -> str:
    package_root = resources.files(__package__)
    return (package_root / relative).read_text(encoding="utf-8")


def _resource_bytes(relative: str) -> bytes:
    package_root = resources.files(__package__)
    return (package_root / relative).read_bytes()


def render_dashboard_html(*, version: str = __version__, refresh_seconds: float = PANEL_REFRESH_SECONDS) -> str:
    """Render the packaged dashboard shell.

    The visual dashboard is intentionally stored as template/CSS/JS/SVG assets
    under ``staqtapp_tds.admin`` instead of a large hand-built string. This
    keeps the admin UI upgradable while preserving the control-plane boundary:
    browser code consumes ``/status.json`` snapshots only.
    """

    template = _resource_text("templates/dashboard.html")
    return (
        template.replace("{version}", html.escape(str(version)))
        .replace("{refresh}", f"{refresh_seconds:.0f}")
    )


# Compatibility token for older tests/imports that checked the panel shell.
HTML = render_dashboard_html()


class AdminPanelServer:
    """Optional localhost browser panel.

    The panel deliberately reads the AdminControl snapshot instead of walking TDS
    structures. Expensive diagnostics should be explicit admin actions, never
    dashboard refresh work.
    """

    def __init__(self, control: AdminControl | None = None, host: str = "127.0.0.1", port: int = 8765):
        self.control = control or AdminControl()
        self.host = host
        self.port = port
        auth = getattr(self.control, "auth", None)
        if hasattr(auth, "assert_safe_for_bind"):
            auth.assert_safe_for_bind(host)

    def _status_snapshot(self) -> dict[str, object]:
        snap = self.control.status()
        obs = snap.get("observation") if isinstance(snap, dict) else None
        if isinstance(obs, dict) and "health" in obs:
            snap["system_health"] = str(obs.get("system_health") or obs["health"].get("state", "healthy")).upper()
        else:
            snap["system_health"] = "HEALTHY"
        snap["panel"] = {
            "mode": "local-only",
            "refresh_seconds": PANEL_REFRESH_SECONDS,
            "snapshot_only": True,
            "deep_diagnostics_manual_only": True,
            "ui": "professional-observability-dashboard",
        }
        snap["server_time"] = time.time()
        return snap

    def _static_asset(self, path: str) -> tuple[bytes, str] | None:
        # Static paths are package resources only; prevent path traversal.
        prefix = "/static/"
        if not path.startswith(prefix):
            return None
        rel = unquote(path[len(prefix):])
        pure = PurePosixPath(rel)
        if pure.is_absolute() or ".." in pure.parts or not rel:
            return None
        resource_rel = f"static/{pure.as_posix()}"
        try:
            data = _resource_bytes(resource_rel)
        except (FileNotFoundError, ModuleNotFoundError, AttributeError):
            return None
        ctype = mimetypes.guess_type(resource_rel)[0] or "application/octet-stream"
        if resource_rel.endswith(".svg"):
            ctype = "image/svg+xml"
        elif resource_rel.endswith(".css"):
            ctype = "text/css"
        elif resource_rel.endswith(".js"):
            ctype = "application/javascript"
        return data, ctype

    def make_handler(self):
        outer = self
        control = self.control

        class Handler(BaseHTTPRequestHandler):
            def _send(self, code: int, body: str | bytes, ctype: str = "text/html"):
                data = body.encode("utf-8") if isinstance(body, str) else body
                self.send_response(code)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.send_header("cache-control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/status.json":
                    self._send(200, dumps_pretty(outer._status_snapshot())[0], "application/json")
                    return
                if self.path.startswith("/static/"):
                    asset = outer._static_asset(self.path)
                    if asset is None:
                        self._send(404, "not found", "text/plain")
                        return
                    data, ctype = asset
                    self._send(200, data, ctype)
                    return
                if self.path in {"/", "/index.html", "/dashboard"}:
                    self._send(200, render_dashboard_html(version=__version__, refresh_seconds=PANEL_REFRESH_SECONDS))
                    return
                self._send(404, "not found", "text/plain")

            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                raw = self.rfile.read(length).decode("utf-8")
                form = parse_qs(raw)
                try:
                    if self.path == "/stage":
                        active = control.registry.active()
                        cand = active.next_generation(
                            chunk_bytes=int(form.get("chunk_bytes", [active.chunk_bytes])[0]),
                            compression=str(form.get("compression", [active.compression])[0]),
                            compression_enabled="compression_enabled" in form,
                            admin_panel_enabled=True,
                            network_mode="local-only",
                        )
                        control.stage_config(cand, control.auth.issue("stage"))
                    elif self.path == "/promote":
                        control.promote_config(control.auth.issue("promote"))
                    elif self.path == "/rollback":
                        control.rollback_config(control.auth.issue("rollback"))
                    else:
                        self._send(404, "not found", "text/plain")
                        return
                    self.send_response(303)
                    self.send_header("location", "/")
                    self.end_headers()
                except Exception as exc:
                    self._send(400, html.escape(str(exc)), "text/plain")

            def log_message(self, fmt, *args):
                return

        return Handler

    def serve_forever(self):
        server = ThreadingHTTPServer((self.host, self.port), self.make_handler())
        print(f"Staqtapp-TDS admin panel: http://{self.host}:{self.port}")
        server.serve_forever()
