"""Launcher helpers for the optional Driver Studio PyQt5 cockpit."""
from __future__ import annotations

import sys
from typing import Any, Sequence

from .availability import require_pyqt5
from .bridge import StudioQtBridge
from .main_window import create_driver_studio_window
from .theme import DEFAULT_STUDIO_QT_THEME, StudioQtTheme


def run_driver_studio_app(
    bundle: Any | None = None,
    *,
    argv: Sequence[str] | None = None,
    bridge: StudioQtBridge | None = None,
    theme: StudioQtTheme | None = None,
) -> int:
    """Run the optional PyQt5 cockpit shell.

    This function is intentionally outside the package console scripts for now;
    v3.1.12 introduces the shell module without making GUI startup part of core
    TDS execution.
    """

    require_pyqt5()
    from PyQt5 import QtWidgets  # type: ignore

    app = QtWidgets.QApplication(list(argv) if argv is not None else sys.argv)
    window = create_driver_studio_window(bridge=bridge, theme=theme or DEFAULT_STUDIO_QT_THEME)
    if bundle is not None:
        window.load_bundle(bundle)
    window.show()
    return int(app.exec_())


__all__ = ["run_driver_studio_app"]
