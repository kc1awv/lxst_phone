"""
Call history window for LXST Phone.

Displays recent call history with filtering and statistics.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QLabel,
    QGroupBox,
    QMessageBox,
    QComboBox,
    QApplication,
)

from lxst_phone.call_history import CallHistory, CallRecord
from lxst_phone.logging_config import get_logger

logger = get_logger("ui.call_history")


def get_theme_colors():
    """Get color palette based on system theme (light or dark mode)."""
    app = QApplication.instance()
    if app:
        palette = app.palette()
        bg_color = palette.color(QPalette.Window)
        is_dark = bg_color.lightness() < 128
    else:
        is_dark = False
    
    if is_dark:
        return {
            'primary': '#5DADE2',
            'success': '#52BE80',
            'danger': '#EC7063',
            'border': '#566573',
            'light': '#34495E',
            'bg': '#2C3E50',
            'fg': '#ECF0F1',
            'card_bg': '#34495E',
        }
    else:
        return {
            'primary': '#4A90E2',
            'success': '#27AE60',
            'danger': '#E74C3C',
            'border': '#BDC3C7',
            'light': '#ECF0F1',
            'bg': '#FFFFFF',
            'fg': '#2C3E50',
            'card_bg': '#FAFAFA',
        }


class CallHistoryWindow(QDialog):
    """Window for viewing call history."""

    callRequested = Signal(str)  # peer_id

    def __init__(self, call_history: CallHistory, parent=None):
        super().__init__(parent)
        self.call_history = call_history

        self.setWindowTitle("Call History")
        self.resize(900, 650)
        
        # Apply modern styling with dynamic colors
        colors = get_theme_colors()
        self.setStyleSheet(f"""
            QWidget {{
                font-size: 11pt;
                color: {colors['fg']};
            }}
            QPushButton {{
                background-color: {colors['primary']};
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 500;
            }}
            QPushButton:hover {{
                opacity: 0.9;
            }}
            QPushButton:disabled {{
                background-color: {colors['border']};
                color: {colors['fg']};
                opacity: 0.5;
            }}
            QPushButton#clearButton {{
                background-color: {colors['danger']};
            }}
            QPushButton#clearButton:hover {{
                opacity: 0.9;
            }}
            QTableWidget {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                background-color: {colors['bg']};
                color: {colors['fg']};
                gridline-color: {colors['light']};
            }}
            QTableWidget::item {{
                padding: 6px;
            }}
            QTableWidget::item:selected {{
                background-color: {colors['primary']};
                color: white;
            }}
            QHeaderView::section {{
                background-color: {colors['light']};
                padding: 8px;
                border: none;
                border-bottom: 2px solid {colors['primary']};
                font-weight: bold;
                color: {colors['primary']};
            }}
            QGroupBox {{
                border: 2px solid {colors['border']};
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 12px;
                font-weight: bold;
                background-color: {colors['card_bg']};
                color: {colors['fg']};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 10px;
                padding: 0 5px;
            }}
        """)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        """Build the UI."""
        layout = QVBoxLayout()
        self.setLayout(layout)

        stats_group = QGroupBox("Statistics")
        stats_layout = QHBoxLayout()
        stats_group.setLayout(stats_layout)

        colors = get_theme_colors()
        self.total_calls_label = QLabel("Total: 0")
        self.total_calls_label.setStyleSheet("font-weight: bold;")
        self.answered_calls_label = QLabel("Answered: 0")
        self.answered_calls_label.setStyleSheet(f"color: {colors['success']}; font-weight: bold;")
        self.missed_calls_label = QLabel("Missed: 0")
        self.missed_calls_label.setStyleSheet(f"color: {colors['danger']}; font-weight: bold;")
        self.total_duration_label = QLabel("Total Duration: 0h 0m")
        self.total_duration_label.setStyleSheet("font-weight: bold;")

        stats_layout.addWidget(self.total_calls_label)
        stats_layout.addWidget(QLabel("|"))
        stats_layout.addWidget(self.answered_calls_label)
        stats_layout.addWidget(QLabel("|"))
        stats_layout.addWidget(self.missed_calls_label)
        stats_layout.addWidget(QLabel("|"))
        stats_layout.addWidget(self.total_duration_label)
        stats_layout.addStretch()

        layout.addWidget(stats_group)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter:"))

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(
            ["All Calls", "Incoming", "Outgoing", "Answered", "Missed"]
        )
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.filter_combo)

        filter_layout.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_list)
        filter_layout.addWidget(refresh_btn)

        layout.addLayout(filter_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["Time", "Direction", "Peer", "Display Name", "Duration", "Status"]
        )

        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSortingEnabled(True)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # Time
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Direction
        header.setSectionResizeMode(2, QHeaderView.Stretch)  # Peer
        header.setSectionResizeMode(3, QHeaderView.Stretch)  # Display Name
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Duration
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Status

        self.table.doubleClicked.connect(self._on_row_double_clicked)

        layout.addWidget(self.table)

        button_layout = QHBoxLayout()

        self.call_btn = QPushButton("Call Selected")
        self.call_btn.setEnabled(False)
        self.call_btn.clicked.connect(self._on_call_clicked)
        self.call_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(self.call_btn)

        button_layout.addStretch()

        clear_btn = QPushButton("Clear History")
        clear_btn.setObjectName("clearButton")
        clear_btn.clicked.connect(self._on_clear_clicked)
        clear_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        close_btn.setCursor(Qt.PointingHandCursor)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        self.table.itemSelectionChanged.connect(self._on_selection_changed)

    def _refresh_list(self) -> None:
        """Refresh the call history list."""
        stats = self.call_history.get_statistics()
        self.total_calls_label.setText(f"Total: {stats['total_calls']}")
        self.answered_calls_label.setText(f"Answered: {stats['answered_calls']}")
        self.missed_calls_label.setText(f"Missed: {stats['missed_calls']}")

        hours = stats["total_duration_sec"] // 3600
        minutes = (stats["total_duration_sec"] % 3600) // 60
        self.total_duration_label.setText(f"Total Duration: {hours}h {minutes}m")

        calls = self.call_history.get_recent_calls(limit=200)

        filter_type = self.filter_combo.currentText()
        if filter_type == "Incoming":
            calls = [c for c in calls if c.direction == "incoming"]
        elif filter_type == "Outgoing":
            calls = [c for c in calls if c.direction == "outgoing"]
        elif filter_type == "Answered":
            calls = [c for c in calls if c.answered]
        elif filter_type == "Missed":
            calls = [c for c in calls if not c.answered]

        self.table.setRowCount(len(calls))
        self.table.setSortingEnabled(False)  # Disable sorting while populating

        for row, call in enumerate(calls):
            try:
                dt = datetime.fromisoformat(call.timestamp)
                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                time_str = call.timestamp

            time_item = QTableWidgetItem(time_str)
            self.table.setItem(row, 0, time_item)

            direction_icon = "<<" if call.direction == "incoming" else ">>"
            direction_item = QTableWidgetItem(
                f"{direction_icon} {call.direction.capitalize()}"
            )
            self.table.setItem(row, 1, direction_item)

            peer_item = QTableWidgetItem(f"{call.peer_id[:16]}...")
            peer_item.setData(Qt.UserRole, call.peer_id)  # Store full ID
            self.table.setItem(row, 2, peer_item)

            name_item = QTableWidgetItem(call.display_name or "Unknown")
            self.table.setItem(row, 3, name_item)

            minutes = call.duration_sec // 60
            seconds = call.duration_sec % 60
            duration_str = f"{minutes}m {seconds}s" if minutes > 0 else f"{seconds}s"
            duration_item = QTableWidgetItem(duration_str)
            duration_item.setData(Qt.UserRole, call.duration_sec)  # For sorting
            self.table.setItem(row, 4, duration_item)

            colors = get_theme_colors()
            if call.answered:
                status_item = QTableWidgetItem("Answered")
                status_item.setForeground(QColor(colors['success']))
            else:
                status_item = QTableWidgetItem("Missed")
                status_item.setForeground(QColor(colors['danger']))
            self.table.setItem(row, 5, status_item)

        self.table.setSortingEnabled(True)  # Re-enable sorting
        self.table.sortItems(0, Qt.DescendingOrder)  # Sort by time descending

        logger.debug(f"Refreshed call history: {len(calls)} calls displayed")

    def _on_filter_changed(self) -> None:
        """Handle filter change."""
        self._refresh_list()

    def _on_selection_changed(self) -> None:
        """Handle selection change."""
        has_selection = len(self.table.selectedItems()) > 0
        self.call_btn.setEnabled(has_selection)

    def _on_row_double_clicked(self) -> None:
        """Handle row double-click (call the peer)."""
        self._on_call_clicked()

    def _on_call_clicked(self) -> None:
        """Handle call button click."""
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            return

        row = selected_rows[0].row()
        peer_item = self.table.item(row, 2)
        peer_id = peer_item.data(Qt.UserRole)

        if peer_id:
            logger.info(f"Call requested for peer: {peer_id[:16]}...")
            self.callRequested.emit(peer_id)
            self.close()

    def _on_clear_clicked(self) -> None:
        """Handle clear history button click."""
        reply = QMessageBox.question(
            self,
            "Clear History",
            "Are you sure you want to clear all call history?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply == QMessageBox.Yes:
            self.call_history.clear_history()
            self._refresh_list()
            logger.info("Call history cleared by user")
