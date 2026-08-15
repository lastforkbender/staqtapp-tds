"""Main launcher for the packaged TDS telemetry Browser."""
from __future__ import annotations

import argparse
import webbrowser
from http.server import ThreadingHTTPServer
from typing import Sequence

from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.admin.workspace import WorkspaceMountError, WorkspaceTelemetrySource


def main(argv: Sequence[str] | None = None) -> int:
    """Start the local telemetry server and open its Browser dashboard."""

    parser = argparse.ArgumentParser(prog="staqtapp-tds")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="serve the telemetry UI without opening a browser window",
    )
    parser.add_argument(
        "--workspace-mount",
        metavar="PATH",
        help=(
            "read observer-only telemetry snapshots from a local workspace "
            "directory produced by WorkspaceTelemetryPublisher"
        ),
    )
    args = parser.parse_args(argv)

    observation_source = None
    if args.workspace_mount is not None:
        try:
            observation_source = WorkspaceTelemetrySource(args.workspace_mount)
        except WorkspaceMountError as exc:
            parser.error(str(exc))

    panel = AdminPanelServer(
        AdminControl(observation_source=observation_source),
        args.host,
        args.port,
    )
    server = ThreadingHTTPServer((panel.host, panel.port), panel.make_handler())
    url = f"http://{panel.host}:{server.server_port}/dashboard"
    print(f"Staqtapp-TDS telemetry UI: {url}")
    if not args.no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


__all__ = ["main"]
