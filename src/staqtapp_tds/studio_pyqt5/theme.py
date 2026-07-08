"""Dark professional Driver Studio PyQt5 theme constants.

The values intentionally mirror the broader TDS Browser telemetry family:
blue, purple, and orange accents on a dark operations-console surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StudioQtTheme:
    """Small immutable theme object for Qt widgets and tests."""

    name: str = "tds-driver-studio-dark"
    background: str = "#10131c"
    panel_background: str = "#151a26"
    panel_raised: str = "#1c2433"
    text_primary: str = "#eef3ff"
    text_secondary: str = "#a8b3c7"
    telemetry_blue: str = "#3aa8ff"
    telemetry_purple: str = "#8f5cff"
    telemetry_orange: str = "#ff9d42"
    danger: str = "#ff5f73"
    success: str = "#5fe3a1"
    border: str = "#2a3346"
    minimum_font_px: int = 12
    body_font_px: int = 13
    title_font_px: int = 16
    summary_font_px: int = 12
    monospace_font_px: int = 12

    def palette(self) -> Mapping[str, str]:
        return {
            "background": self.background,
            "panel_background": self.panel_background,
            "panel_raised": self.panel_raised,
            "text_primary": self.text_primary,
            "text_secondary": self.text_secondary,
            "telemetry_blue": self.telemetry_blue,
            "telemetry_purple": self.telemetry_purple,
            "telemetry_orange": self.telemetry_orange,
            "danger": self.danger,
            "success": self.success,
            "border": self.border,
        }

    def stylesheet(self) -> str:
        """Return a compact Qt stylesheet for the shell cockpit."""

        return f"""
        QMainWindow {{ background: {self.background}; color: {self.text_primary}; }}
        QWidget {{ background: {self.background}; color: {self.text_primary}; font-family: Inter, Segoe UI, Arial; font-size: {self.body_font_px}px; }}
        QDockWidget {{ titlebar-close-icon: none; titlebar-normal-icon: none; color: {self.text_primary}; }}
        QDockWidget::title {{ background: {self.panel_raised}; padding: 6px; border: 1px solid {self.border}; }}
        QFrame#StudioPanel, QFrame#ManualBuilderPanel {{ background: {self.panel_background}; border: 1px solid {self.border}; border-radius: 10px; }}
        QLabel {{ background: transparent; }}
        QLabel#PanelTitle {{ color: {self.text_primary}; font-size: {self.title_font_px}px; font-weight: 700; padding-bottom: 2px; }}
        QLabel#PanelSummary, QLabel#FieldHelp {{ color: {self.text_secondary}; font-size: {self.summary_font_px}px; line-height: 1.35; }}
        QGroupBox {{ border: 1px solid {self.border}; border-radius: 8px; margin-top: 12px; padding: 12px 8px 8px 8px; color: {self.text_primary}; font-weight: 700; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {self.telemetry_blue}; }}
        QScrollArea {{ border: 0; background: transparent; }}
        QScrollBar:vertical {{ background: {self.background}; width: 10px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {self.border}; border-radius: 5px; min-height: 28px; }}
        QPushButton {{ background: {self.panel_raised}; border: 1px solid {self.border}; border-radius: 6px; padding: 7px 12px; min-height: 30px; }}
        QPushButton:hover {{ border-color: {self.telemetry_blue}; }}
        QPushButton#ApproveAction {{ border-color: {self.telemetry_blue}; }}
        QPushButton#HoldAction {{ border-color: {self.telemetry_orange}; }}
        QPushButton#RejectAction {{ border-color: {self.danger}; }}
        QPushButton#QuarantineAction {{ border-color: {self.telemetry_purple}; }}
        QTableWidget {{ background: {self.panel_background}; gridline-color: {self.border}; alternate-background-color: {self.panel_raised}; }}
        QHeaderView::section {{ background: {self.panel_raised}; color: {self.text_secondary}; border: 1px solid {self.border}; padding: 4px; }}
        QTextEdit, QPlainTextEdit {{ background: {self.panel_background}; border: 1px solid {self.border}; border-radius: 8px; font-size: {self.monospace_font_px}px; padding: 6px; selection-background-color: {self.telemetry_purple}; }}
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ min-height: 30px; padding: 4px 7px; border: 1px solid {self.border}; border-radius: 6px; background: {self.panel_raised}; }}
        QCheckBox {{ spacing: 8px; }}
        QTextEdit#ManualBuilderSource, QPlainTextEdit#ManualBuilderPreview {{ min-height: 220px; }}
        """.strip()


DEFAULT_STUDIO_QT_THEME = StudioQtTheme()
