"""Optional PyQt5 availability helpers for Driver Studio.

The v3.1.12 Studio shell is allowed to render a cockpit when PyQt5 is installed,
but the core TDS package and tests must remain usable without a GUI dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib.util import find_spec


class PyQt5UnavailableError(RuntimeError):
    """Raised only when a caller explicitly asks to construct the Qt shell."""


@dataclass(frozen=True, slots=True)
class PyQt5Availability:
    """Stable report used by tests, launchers, and diagnostics."""

    available: bool
    reason: str
    import_name: str = "PyQt5"


def pyqt5_availability() -> PyQt5Availability:
    """Return whether PyQt5 can be imported without importing it eagerly."""

    if find_spec("PyQt5") is None:
        return PyQt5Availability(False, "PyQt5 is not installed; Studio shell remains in headless bridge mode")
    return PyQt5Availability(True, "PyQt5 import target is available")


def pyqt5_available() -> bool:
    """Boolean convenience wrapper for optional shell launchers."""

    return pyqt5_availability().available


def require_pyqt5() -> None:
    """Fail explicitly when a caller tries to create a GUI without PyQt5."""

    availability = pyqt5_availability()
    if not availability.available:
        raise PyQt5UnavailableError(availability.reason)
