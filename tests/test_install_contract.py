from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_standard_install_requires_ui_and_preserves_gui_extra_alias():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]

    assert "PyQt5>=5.15" in project["dependencies"]
    assert project["optional-dependencies"]["gui"] == []
    assert project["scripts"]["staqtapp-tds-admin"] == "staqtapp_tds.admin.console:main"
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
