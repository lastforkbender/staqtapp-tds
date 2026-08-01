from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.10 CI job
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_standard_install_includes_main_telemetry_ui_launcher():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert "PyQt5>=5.15" in project["dependencies"]
    assert project["optional-dependencies"]["gui"] == []
    assert project["scripts"]["staqtapp-tds"] == "staqtapp_tds.admin.app:main"
    assert project["scripts"]["staqtapp-tds-admin"] == "staqtapp_tds.admin.console:main"
    assert project["scripts"]["staqtapp-tds-foundation-closure"] == (
        "staqtapp_tds.native.foundation:main"
    )
    assert project["scripts"]["staqtapp-tds-generation-audit"] == (
        "staqtapp_tds.generation.audit:main"
    )
    assert metadata["tool"]["setuptools"]["package-data"]["staqtapp_tds.admin"] == [
        "templates/*.html",
        "static/css/*.css",
        "static/js/*.js",
        "static/icons/*.svg",
        "static/i18n/*.json",
    ]


def test_native_extensions_remain_explicitly_opt_in():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    setup_source = (ROOT / "setup.py").read_text(encoding="utf-8")

    assert project["optional-dependencies"]["native"] == []
    assert 'os.environ.get("STAQTAPP_TDS_BUILD_NATIVE", "")' in setup_source
    assert "setup(ext_modules=ext_modules if native_enabled else [])" in setup_source


def test_main_launcher_opens_the_telemetry_browser(monkeypatch):
    from staqtapp_tds.admin import app

    events: list[object] = []

    class FakeServer:
        server_port = 8765

        def __init__(self, address, handler):
            events.append(("server", address, handler))

        def serve_forever(self):
            events.append("serve")

        def server_close(self):
            events.append("close")

    monkeypatch.setattr(app, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(app.webbrowser, "open", lambda url: events.append(("open", url)))

    assert app.main([]) == 0
    assert ("open", "http://127.0.0.1:8765/dashboard") in events
    assert events[-2:] == ["serve", "close"]
