"""Optional PyQt5 Driver Studio cockpit shell.

Importing this module is safe without PyQt5. Constructing the GUI requires
PyQt5 and raises a clear error otherwise. The window renders snapshots, drives
Manual Builder preview/proposal interactions through the Studio bridge, and
sends review-action requests through the existing safe path; it does not own
driver authority.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from staqtapp_tds.drivers.review import ReviewAction
from staqtapp_tds.drivers.studio import StudioPanelKind
from .availability import PyQt5UnavailableError, require_pyqt5
from .bridge import StudioQtBridge, StudioQtShellState
from .hydration import StudioFormField
from .manual_builder_runtime import StudioManualBuilderUIRuntime
from .theme import DEFAULT_STUDIO_QT_THEME, StudioQtTheme

try:  # pragma: no cover - exercised only in environments with PyQt5.
    from PyQt5 import QtCore, QtWidgets
except Exception:  # pragma: no cover - CI intentionally allows no PyQt5.
    QtCore = None  # type: ignore[assignment]
    QtWidgets = None  # type: ignore[assignment]


if QtWidgets is not None:  # pragma: no cover - optional GUI path.

    class DriverStudioMainWindow(QtWidgets.QMainWindow):
        """Browser-like PyQt5 cockpit for Driver Studio evidence snapshots."""

        def __init__(self, *, bridge: StudioQtBridge | None = None, theme: StudioQtTheme | None = None) -> None:
            super().__init__()
            self.bridge = bridge or StudioQtBridge()
            self.theme = theme or DEFAULT_STUDIO_QT_THEME
            self.manual_builder_runtime = self.bridge.manual_builder_ui_runtime()
            self.setWindowTitle("Staqtapp-TDS Driver Studio")
            self.setMinimumSize(1440, 900)
            self.resize(1560, 960)
            self.setStyleSheet(self.theme.stylesheet())
            self._panels: dict[StudioPanelKind, Any] = {}
            self._build_shell()
            self.refresh_state(self.bridge.shell_state())

        def _build_shell(self) -> None:
            central = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(central)
            layout.setContentsMargins(14, 12, 14, 10)
            layout.setSpacing(8)
            header = QtWidgets.QLabel("Driver Studio Cockpit Shell")
            header.setObjectName("PanelTitle")
            self.status_label = QtWidgets.QLabel("No evidence bundle loaded")
            self.status_label.setObjectName("PanelSummary")
            self.status_label.setWordWrap(True)
            layout.addWidget(header)
            layout.addWidget(self.status_label)
            self.setCentralWidget(central)

            for kind in StudioPanelKind:
                dock = QtWidgets.QDockWidget(kind.value.replace("_", " ").title(), self)
                dock.setObjectName(f"StudioDock_{kind.value}")
                dock.setMinimumWidth(360 if kind is not StudioPanelKind.MANUAL_DRIVER_BUILDER else 520)
                dock.setFeatures(
                    QtWidgets.QDockWidget.DockWidgetMovable
                    | QtWidgets.QDockWidget.DockWidgetFloatable
                    | QtWidgets.QDockWidget.DockWidgetClosable
                )
                panel = _ManualBuilderPanelWidget(self.manual_builder_runtime) if kind is StudioPanelKind.MANUAL_DRIVER_BUILDER else _PanelWidget(kind)
                dock.setWidget(panel)
                self._panels[kind] = panel
                self.addDockWidget(_dock_area(kind), dock)

        def load_bundle(self, bundle: Any, *, selected_driver_id: str | None = None) -> StudioQtShellState:
            state = self.bridge.load_bundle(bundle, selected_driver_id=selected_driver_id)
            self.refresh_state(state)
            return state

        def refresh_state(self, state: StudioQtShellState | None = None) -> StudioQtShellState:
            state = state or self.bridge.shell_state()
            self.status_label.setText(
                f"{state.status} | bundle={state.bundle_id or 'none'} | hash={state.console_hash or 'none'}"
            )
            hydrated = self.bridge.hydrated_shell_state()
            for panel in hydrated.panels:
                widget = self._panels.get(panel.kind)
                if widget is not None:
                    widget.render(panel)
            return state

        def submit_action_from_selection(
            self,
            action: ReviewAction | str,
            *,
            reviewer_id: str = "studio-admin",
            rationale: str = "",
        ) -> Any:
            state = self.bridge.shell_state()
            if not state.selected_driver_id:
                raise RuntimeError("select a driver before submitting a Studio review action")
            request = self.bridge.build_action_request(
                state.selected_driver_id,
                action,
                reviewer_id=reviewer_id,
                rationale=rationale,
                source_panel=StudioPanelKind.DRIVER_QUEUE,
            )
            return self.bridge.submit_review_action(request)


    class _PanelWidget(QtWidgets.QFrame):
        def __init__(self, kind: StudioPanelKind) -> None:
            super().__init__()
            self.kind = kind
            self.setObjectName("StudioPanel")
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)
            self.title = QtWidgets.QLabel(kind.value.replace("_", " ").title())
            self.title.setObjectName("PanelTitle")
            self.title.setWordWrap(True)
            self.summary = QtWidgets.QLabel("")
            self.summary.setObjectName("PanelSummary")
            self.summary.setWordWrap(True)
            self.body = QtWidgets.QTextEdit()
            self.body.setReadOnly(True)
            self.body.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
            layout.addWidget(self.title)
            layout.addWidget(self.summary)
            layout.addWidget(self.body, stretch=1)

        def render(self, panel: Any) -> None:
            self.title.setText(panel.title)
            self.summary.setText(f"{panel.status} | {panel.summary}")
            payload = {
                "kind": panel.kind.value,
                "surface": panel.primary_surface,
                "severity": getattr(panel, "severity", "info"),
                "columns": [getattr(column, "key", str(column)) for column in getattr(panel, "columns", ())],
                "rows": list(panel.rows),
                "cards": [getattr(card, "title", str(card)) for card in getattr(panel, "cards", ())],
                "timeline": [getattr(item, "label", str(item)) for item in getattr(panel, "timeline", ())],
                "actions": [getattr(action, "action_id", str(action)) for action in getattr(panel, "actions", ())],
                "form_fields": [getattr(field, "name", str(field)) for field in getattr(panel, "form_fields", ())],
                "metrics": dict(panel.metrics),
                "warnings": list(panel.warnings),
                "admin_action_buttons": bool(getattr(panel, "actions", ())),
            }
            self.body.setPlainText(json.dumps(payload, indent=2, sort_keys=True))


    class _ManualBuilderPanelWidget(QtWidgets.QFrame):
        """Readable Manual Builder workbench with scroll-safe field containment."""

        def __init__(self, runtime: StudioManualBuilderUIRuntime) -> None:
            super().__init__()
            self.runtime = runtime
            self.setObjectName("ManualBuilderPanel")
            self._widgets: dict[str, Any] = {}
            self._build()
            self._render_quality()

        def _build(self) -> None:
            outer = QtWidgets.QVBoxLayout(self)
            outer.setContentsMargins(12, 12, 12, 12)
            outer.setSpacing(8)
            title = QtWidgets.QLabel("Manual Driver Builder")
            title.setObjectName("PanelTitle")
            title.setWordWrap(True)
            self.summary = QtWidgets.QLabel("Edit bounded task fields, preview deterministic TDDL, then route proposal-only work to Driver Foundry.")
            self.summary.setObjectName("PanelSummary")
            self.summary.setWordWrap(True)
            outer.addWidget(title)
            outer.addWidget(self.summary)

            splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
            splitter.setChildrenCollapsible(False)
            outer.addWidget(splitter, stretch=1)

            self.form_scroll = QtWidgets.QScrollArea()
            self.form_scroll.setWidgetResizable(True)
            self.form_scroll.setMinimumWidth(460)
            form_host = QtWidgets.QWidget()
            form_layout = QtWidgets.QVBoxLayout(form_host)
            form_layout.setContentsMargins(6, 6, 10, 6)
            form_layout.setSpacing(10)
            core_box = QtWidgets.QGroupBox("Core Proposal Fields")
            advanced_box = QtWidgets.QGroupBox("Advanced Search / Extraction Fields")
            core_form = QtWidgets.QFormLayout(core_box)
            advanced_form = QtWidgets.QFormLayout(advanced_box)
            for form in (core_form, advanced_form):
                form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
                form.setFormAlignment(QtCore.Qt.AlignTop)
                form.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)
                form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
                form.setVerticalSpacing(8)
            for field in self.runtime.form_fields():
                row = self._field_row(field)
                target = core_form if field.name in _CORE_FIELD_NAMES else advanced_form
                target.addRow(row[0], row[1])
            form_layout.addWidget(core_box)
            form_layout.addWidget(advanced_box)
            form_layout.addStretch(1)
            self.form_scroll.setWidget(form_host)
            splitter.addWidget(self.form_scroll)

            right = QtWidgets.QWidget()
            right_layout = QtWidgets.QVBoxLayout(right)
            right_layout.setContentsMargins(10, 6, 6, 6)
            right_layout.setSpacing(8)
            self.preview_text = QtWidgets.QPlainTextEdit()
            self.preview_text.setReadOnly(True)
            self.preview_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            self.preview_text.setMinimumWidth(520)
            self.preview_text.setPlaceholderText("Previewed deterministic TDDL appears here.")
            self.status = QtWidgets.QTextEdit()
            self.status.setReadOnly(True)
            self.status.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
            self.status.setMaximumHeight(170)
            button_row = QtWidgets.QHBoxLayout()
            self.preview_button = QtWidgets.QPushButton("Preview TDDL")
            self.propose_button = QtWidgets.QPushButton("Route to Foundry")
            self.preview_button.clicked.connect(self._preview_clicked)
            self.propose_button.clicked.connect(self._propose_clicked)
            button_row.addWidget(self.preview_button)
            button_row.addWidget(self.propose_button)
            button_row.addStretch(1)
            right_layout.addLayout(button_row)
            right_layout.addWidget(self.preview_text, stretch=2)
            right_layout.addWidget(self.status, stretch=0)
            splitter.addWidget(right)
            splitter.setSizes([520, 760])

        def _field_row(self, field: StudioFormField) -> tuple[Any, Any]:
            label = QtWidgets.QLabel(field.label + (" *" if field.required else ""))
            label.setWordWrap(True)
            wrapper = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(wrapper)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            widget = self._make_editor(field)
            layout.addWidget(widget)
            if field.help_text:
                help_label = QtWidgets.QLabel(field.help_text)
                help_label.setObjectName("FieldHelp")
                help_label.setWordWrap(True)
                layout.addWidget(help_label)
            self._widgets[field.name] = widget
            return label, wrapper

        def _make_editor(self, field: StudioFormField) -> Any:
            if field.widget == "combo_box":
                widget = QtWidgets.QComboBox()
                widget.addItems([str(item) for item in field.options])
                index = widget.findText(str(field.default))
                if index >= 0:
                    widget.setCurrentIndex(index)
                return widget
            if field.widget == "spin_box":
                widget = QtWidgets.QSpinBox()
                widget.setRange(int(field.minimum or 0), int(field.maximum or 999999))
                widget.setValue(int(field.default))
                return widget
            if field.widget == "double_spin_box":
                widget = QtWidgets.QDoubleSpinBox()
                widget.setRange(float(field.minimum or 0.0), float(field.maximum or 1.0))
                widget.setDecimals(3)
                widget.setSingleStep(0.05)
                widget.setValue(float(field.default))
                return widget
            if field.widget == "check_box":
                widget = QtWidgets.QCheckBox()
                widget.setChecked(bool(field.default))
                return widget
            if field.widget == "text_edit":
                widget = QtWidgets.QTextEdit()
                widget.setAcceptRichText(False)
                widget.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
                widget.setMinimumHeight(70 if field.name != "description" else 92)
                widget.setPlainText(str(field.default))
                return widget
            widget = QtWidgets.QLineEdit(str(field.default))
            widget.setMinimumWidth(260)
            return widget

        def _values(self) -> Mapping[str, Any]:
            out: dict[str, Any] = {}
            for name, widget in self._widgets.items():
                if isinstance(widget, QtWidgets.QComboBox):
                    out[name] = widget.currentText()
                elif isinstance(widget, QtWidgets.QSpinBox) or isinstance(widget, QtWidgets.QDoubleSpinBox):
                    out[name] = widget.value()
                elif isinstance(widget, QtWidgets.QCheckBox):
                    out[name] = widget.isChecked()
                elif isinstance(widget, QtWidgets.QTextEdit):
                    out[name] = widget.toPlainText()
                elif isinstance(widget, QtWidgets.QLineEdit):
                    out[name] = widget.text()
            return out

        def _preview_clicked(self) -> None:
            state = self.runtime.preview_form_payload(self._values())
            self._render_packet(state)

        def _propose_clicked(self) -> None:
            state = self.runtime.propose_form_payload(self._values())
            self._render_packet(state)

        def _render_packet(self, packet: Any) -> None:
            self.preview_text.setPlainText(packet.source)
            self.status.setPlainText(json.dumps(packet.signal_payload(), indent=2, sort_keys=True))

        def _render_quality(self) -> None:
            review = self.runtime.quality_review()
            self.status.setPlainText(json.dumps(review.signal_payload(), indent=2, sort_keys=True))

        def render(self, panel: Any) -> None:
            self.summary.setText(f"{panel.status} | {panel.summary}")


    _CORE_FIELD_NAMES = {
        "driver_id",
        "description",
        "driver_version",
        "kind",
        "safety",
        "scan_scope",
        "recursive",
        "scan_limit",
        "max_depth",
        "timeout_ms",
    }


    def _dock_area(kind: StudioPanelKind) -> Any:
        if kind in {StudioPanelKind.DRIVER_QUEUE}:
            return QtCore.Qt.LeftDockWidgetArea
        if kind in {StudioPanelKind.EXPORT_INTEGRITY, StudioPanelKind.EVENT_CONSOLE}:
            return QtCore.Qt.BottomDockWidgetArea
        if kind in {StudioPanelKind.AUDIT_TRAIL, StudioPanelKind.EVIDENCE_TIMELINE, StudioPanelKind.RISK_CARD, StudioPanelKind.REGISTRY_STATE}:
            return QtCore.Qt.RightDockWidgetArea
        return QtCore.Qt.TopDockWidgetArea

else:

    class DriverStudioMainWindow:  # type: ignore[no-redef]
        """Placeholder that explains the optional PyQt5 dependency."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            require_pyqt5()
            raise PyQt5UnavailableError("PyQt5 is unavailable")


def create_driver_studio_window(
    *,
    bridge: StudioQtBridge | None = None,
    theme: StudioQtTheme | None = None,
) -> DriverStudioMainWindow:
    """Create the real Qt main window when PyQt5 is installed."""

    require_pyqt5()
    return DriverStudioMainWindow(bridge=bridge, theme=theme)
