"""Custom SVG iconography for the Driver Studio shell.

No emoji or ASCII icons are used. These compact SVG strings can be rendered by
QtSvg when present or inspected by tests and external launchers.
"""
from __future__ import annotations

from typing import Mapping

_ICON_TEMPLATE = """<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"24\" height=\"24\" viewBox=\"0 0 24 24\" role=\"img\" aria-label=\"{label}\"><defs><linearGradient id=\"g\" x1=\"2\" x2=\"22\" y1=\"2\" y2=\"22\"><stop stop-color=\"#3aa8ff\"/><stop offset=\"0.58\" stop-color=\"#8f5cff\"/><stop offset=\"1\" stop-color=\"#ff9d42\"/></linearGradient></defs>{body}</svg>"""


def _svg(label: str, body: str) -> str:
    return _ICON_TEMPLATE.format(label=label, body=body)


STUDIO_SVG_ICONS: Mapping[str, str] = {
    "driver_queue": _svg(
        "Driver evidence queue",
        '<rect x="4" y="5" width="16" height="4" rx="1.5" fill="url(#g)" opacity="0.95"/><rect x="4" y="11" width="13" height="3" rx="1.5" fill="url(#g)" opacity="0.68"/><rect x="4" y="16" width="10" height="3" rx="1.5" fill="url(#g)" opacity="0.44"/>',
    ),
    "evidence_bundle": _svg(
        "Evidence bundle viewer",
        '<path d="M6 4h9l3 3v13H6z" fill="none" stroke="url(#g)" stroke-width="1.7"/><path d="M15 4v4h4" fill="none" stroke="#3aa8ff" stroke-width="1.3"/><circle cx="10" cy="13" r="2.2" fill="url(#g)"/>',
    ),
    "audit_trail": _svg(
        "Audit trail panel",
        '<path d="M6 6h12M6 12h12M6 18h12" stroke="url(#g)" stroke-width="1.8" stroke-linecap="round"/><circle cx="6" cy="6" r="2" fill="#3aa8ff"/><circle cx="6" cy="12" r="2" fill="#8f5cff"/><circle cx="6" cy="18" r="2" fill="#ff9d42"/>',
    ),
    "evidence_timeline": _svg(
        "Evidence timeline",
        '<path d="M12 4v16" stroke="url(#g)" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="6" r="2.1" fill="#3aa8ff"/><circle cx="12" cy="12" r="2.1" fill="#8f5cff"/><circle cx="12" cy="18" r="2.1" fill="#ff9d42"/><path d="M14.5 6h4M5.5 12H10M14.5 18h4" stroke="#a8b3c7" stroke-width="1.2" stroke-linecap="round"/>',
    ),
    "fixture_replay": _svg(
        "Fixture replay summary",
        '<path d="M8 5l10 7-10 7z" fill="url(#g)"/><path d="M5 5v14" stroke="#3aa8ff" stroke-width="2" stroke-linecap="round"/>',
    ),
    "risk_card": _svg(
        "Risk card inspector",
        '<path d="M12 3l9 16H3z" fill="none" stroke="url(#g)" stroke-width="1.8"/><path d="M12 8v5" stroke="#ff9d42" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="16" r="1.1" fill="#ff9d42"/>',
    ),
    "registry_state": _svg(
        "Registry state observer",
        '<circle cx="12" cy="12" r="7" fill="none" stroke="url(#g)" stroke-width="1.8"/><path d="M8 12h8M12 8v8" stroke="#8f5cff" stroke-width="1.6" stroke-linecap="round"/>',
    ),
    "export_integrity": _svg(
        "Export integrity verifier",
        '<path d="M5 12l4 4 10-10" fill="none" stroke="url(#g)" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/><rect x="4" y="4" width="16" height="16" rx="4" fill="none" stroke="#3aa8ff" stroke-width="1.2" opacity="0.45"/>',
    ),
    "export_audit_console": _svg(
        "Export audit console",
        '<rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="url(#g)" stroke-width="1.6"/><path d="M7 8h7M7 12h10M7 16h6" stroke="#a8b3c7" stroke-width="1.2" stroke-linecap="round"/><path d="M16 7l3 3-3 3" fill="none" stroke="#ff9d42" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    ),
    "manual_driver_builder": _svg(
        "Manual driver builder",
        '<rect x="4" y="4" width="16" height="16" rx="3" fill="none" stroke="url(#g)" stroke-width="1.6"/><path d="M8 8h8M8 12h5M8 16h8" stroke="#a8b3c7" stroke-width="1.2" stroke-linecap="round"/><path d="M16 11l3 2-3 2z" fill="url(#g)"/>',
    ),
    "event_console": _svg(
        "Bottom event console",
        '<rect x="4" y="5" width="16" height="14" rx="3" fill="none" stroke="url(#g)" stroke-width="1.6"/><path d="M7 9h4M7 13h10M7 16h7" stroke="#a8b3c7" stroke-width="1.3" stroke-linecap="round"/>',
    ),
    "studio_shell": _svg(
        "Driver Studio cockpit shell",
        '<rect x="3" y="4" width="18" height="16" rx="3" fill="none" stroke="url(#g)" stroke-width="1.7"/><path d="M3 9h18M9 9v11" stroke="#3aa8ff" stroke-width="1.2"/><circle cx="6" cy="6.5" r="1" fill="#ff9d42"/>',
    ),
}


def studio_svg_icon(name: str) -> str:
    """Return a named Studio SVG icon or raise KeyError for unknown names."""

    return STUDIO_SVG_ICONS[name]
