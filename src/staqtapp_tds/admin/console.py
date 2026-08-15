from __future__ import annotations
import argparse, json
from staqtapp_tds import TDSFileSystem
from staqtapp_tds.admin.control import AdminControl
from staqtapp_tds.tds_json import dumps_pretty
from staqtapp_tds.admin.panel import AdminPanelServer
from staqtapp_tds.admin.workspace import WorkspaceMountError, WorkspaceTelemetrySource
from staqtapp_tds.verify import verify


def main(argv=None):
    p = argparse.ArgumentParser(prog="staqtapp-tds-admin")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--sample", action="store_true", help="create a small in-memory TDS sample before verification")
    serve = sub.add_parser("serve-panel")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument(
        "--workspace-mount",
        metavar="PATH",
        help="read observer-only telemetry snapshots from a local workspace directory",
    )
    args = p.parse_args(argv)
    observation_source = None
    if args.cmd == "serve-panel" and args.workspace_mount is not None:
        try:
            observation_source = WorkspaceTelemetrySource(args.workspace_mount)
        except WorkspaceMountError as exc:
            p.error(str(exc))
    control = AdminControl(observation_source=observation_source)
    if args.cmd == "status":
        print(dumps_pretty(control.status())[0], end="")
    elif args.cmd == "verify":
        fs = TDSFileSystem("verify_root")
        if args.sample:
            fs.write_result("sample", b"staqtapp-tds")
        print(dumps_pretty(verify(fs).to_dict())[0], end="")
    elif args.cmd == "serve-panel":
        AdminPanelServer(control, args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
