"""
Main Window for LXST Phone.

Includes:
- Menu bar with File and View menus
- Connection status indicators
- Security banner
- Call quality metrics
- Audio device selection with AGC and filter controls
- Codec profile selection
- Event log view
"""

import time
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Slot, Signal, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QGroupBox,
    QMenuBar,
    QFileDialog,
    QInputDialog,
    QComboBox,
    QStackedWidget,
    QPlainTextEdit,
    QGridLayout,
    QCheckBox,
    QSlider,
    QSpinBox,
    QApplication,
)


def get_theme_colors():
    """Get color palette based on system theme (light or dark mode)."""
    # Detect if we're in dark mode
    app = QApplication.instance()
    if app:
        palette = app.palette()
        # Check if window background is dark
        bg_color = palette.color(QPalette.Window)
        is_dark = bg_color.lightness() < 128
    else:
        is_dark = False
    
    if is_dark:
        # Dark mode color palette
        return {
            'primary': '#5DADE2',      # Lighter blue for dark backgrounds
            'success': '#52BE80',      # Lighter green
            'warning': '#F8C471',      # Lighter orange
            'danger': '#EC7063',       # Lighter red
            'info': '#5DADE2',         # Light blue
            'dark': '#ECF0F1',         # Light text for dark mode
            'light': '#34495E',        # Dark backgrounds
            'border': '#566573',       # Darker border
            'verified': '#BB8FCE',     # Lighter purple
            'bg': '#2C3E50',           # Dark background
            'fg': '#ECF0F1',           # Light foreground/text
            'card_bg': '#34495E',      # Card background
            'hover_bg': '#48566A',     # Hover state
        }
    else:
        # Light mode color palette
        return {
            'primary': '#4A90E2',      # Friendly blue
            'success': '#27AE60',      # Green
            'warning': '#F39C12',      # Orange
            'danger': '#E74C3C',       # Red
            'info': '#3498DB',         # Light blue
            'dark': '#2C3E50',         # Dark text
            'light': '#ECF0F1',        # Light backgrounds
            'border': '#BDC3C7',       # Border gray
            'verified': '#9B59B6',     # Purple
            'bg': '#FFFFFF',           # White background
            'fg': '#2C3E50',           # Dark foreground/text
            'card_bg': '#FAFAFA',      # Card background
            'hover_bg': '#ECF0F1',     # Hover state
        }

import RNS
from LXST.Primitives.Telephony import Profiles

from lxst_phone.logging_config import get_logger
from lxst_phone.core.telephone import TelephoneManager
from lxst_phone.config import Config
from lxst_phone.ui.security_dialogs import (
    show_sas_verification,
    warn_unverified_peer,
)

logger = get_logger("ui")


class MainWindow(QWidget):
    """Main window with full feature set including AGC and audio filters."""

    def __init__(
        self,
        telephone: TelephoneManager,
        local_id: str,
        config: Config,
        lxmf_discovery=None,
        lxmf_announcer=None,
        config_dir=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.telephone = telephone
        self.lxmf_discovery = lxmf_discovery
        self.lxmf_announcer = lxmf_announcer
        self.local_id = local_id
        self.config = config
        self.config_dir = config_dir
        self._event_history: list[str] = []
        self._call_start_time: float | None = None

        from lxst_phone.peers_storage import PeersStorage

        peers_path = None
        if config_dir:
            peers_path = Path(config_dir) / "peers.json"
        self.peers_storage = PeersStorage(storage_path=peers_path)
        self.peers_storage.load()

        from lxst_phone.call_history import CallHistory

        history_path = None
        if config_dir:
            history_path = Path(config_dir) / "call_history.json"
        self.call_history = CallHistory(
            storage_path=history_path, identity=telephone.identity
        )
        self.call_history.load()

        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self._update_connection_status)
        self.connection_timer.setInterval(2000)  # Update every 2 seconds
        self.connection_timer.start()

        self.call_timer = QTimer()
        self.call_timer.timeout.connect(self._update_call_timer)
        self.call_timer.setInterval(1000)  # Update every second

        self.setWindowTitle("LXST Phone")
        w, h = self.config.window_geometry
        self.resize(w, h)
        
        # Apply modern window styling
        self.setStyleSheet(self._get_global_stylesheet())

        self.telephone.call_ringing.connect(self.on_call_ringing)
        self.telephone.call_established.connect(self.on_call_established)
        self.telephone.call_ended.connect(self.on_call_ended)
        self.telephone.call_busy.connect(self.on_call_busy)
        self.telephone.call_rejected.connect(self.on_call_rejected)

        if self.lxmf_discovery:
            self.lxmf_discovery.peer_discovered.connect(self.on_lxmf_peer_discovered)
            logger.info("Connected LXMF peer discovery handler")

        self._build_ui()
        self._update_connection_status()

        logger.info(f"MainWindow initialized for {local_id}")

    def _get_global_stylesheet(self) -> str:
        """Return global stylesheet for modern UI."""
        colors = get_theme_colors()
        return f"""
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
                min-height: 28px;
            }}
            
            QPushButton:hover {{
                background-color: {colors['info']};
            }}
            
            QPushButton:pressed {{
                background-color: {colors['primary']};
                opacity: 0.8;
            }}
            
            QPushButton:disabled {{
                background-color: {colors['border']};
                color: {colors['border']};
            }}
            
            QPushButton#callButton {{
                background-color: {colors['success']};
                font-size: 12pt;
                font-weight: bold;
                padding: 12px 24px;
            }}
            
            QPushButton#callButton:hover {{
                opacity: 0.9;
            }}
            
            QPushButton#hangupButton {{
                background-color: {colors['danger']};
                font-size: 12pt;
                font-weight: bold;
                padding: 12px 24px;
            }}
            
            QPushButton#hangupButton:hover {{
                opacity: 0.9;
            }}
            
            QPushButton#answerButton {{
                background-color: {colors['success']};
                font-size: 12pt;
                font-weight: bold;
                padding: 12px 24px;
            }}
            
            QPushButton#answerButton:hover {{
                opacity: 0.9;
            }}
            
            QPushButton#rejectButton {{
                background-color: {colors['warning']};
                font-size: 12pt;
                font-weight: bold;
                padding: 12px 24px;
            }}
            
            QPushButton#rejectButton:hover {{
                opacity: 0.9;
            }}
            
            QPushButton#verifyButton {{
                background-color: {colors['verified']};
                font-size: 12pt;
                font-weight: bold;
                padding: 12px 24px;
            }}
            
            QPushButton#verifyButton:hover {{
                opacity: 0.9;
            }}
            
            QLineEdit {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                padding: 8px;
                background-color: {colors['bg']};
                color: {colors['fg']};
                selection-background-color: {colors['primary']};
                selection-color: white;
            }}
            
            QLineEdit:focus {{
                border: 2px solid {colors['primary']};
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
                color: {colors['fg']};
            }}
            
            QComboBox {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                padding: 6px;
                background-color: {colors['bg']};
                color: {colors['fg']};
            }}
            
            QComboBox:focus {{
                border: 2px solid {colors['primary']};
            }}
            
            QComboBox::drop-down {{
                border: none;
                padding-right: 4px;
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {colors['bg']};
                color: {colors['fg']};
                selection-background-color: {colors['primary']};
                selection-color: white;
            }}
            
            QLabel {{
                color: {colors['fg']};
            }}
            
            QLabel#statusLabel {{
                font-size: 13pt;
                font-weight: 600;
                color: {colors['fg']};
            }}
            
            QLabel#titleLabel {{
                font-size: 18pt;
                font-weight: bold;
                color: {colors['primary']};
                padding: 8px;
            }}
            
            QCheckBox {{
                color: {colors['fg']};
            }}
            
            QPlainTextEdit {{
                border: 2px solid {colors['border']};
                border-radius: 6px;
                background-color: {colors['card_bg']};
                color: {colors['fg']};
                font-family: 'Courier New', monospace;
            }}
        """

    def _build_ui(self) -> None:
        """Build the UI."""
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        menu_bar = QMenuBar()

        file_menu = menu_bar.addMenu("&File")
        export_action = file_menu.addAction("Export Identity...")
        export_action.triggered.connect(self.on_export_identity)
        import_action = file_menu.addAction("Import Identity...")
        import_action.triggered.connect(self.on_import_identity)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        view_menu = menu_bar.addMenu("&View")
        history_action = view_menu.addAction("Call History...")
        history_action.triggered.connect(self.on_show_history)
        peers_action = view_menu.addAction("Discovered Peers...")
        peers_action.triggered.connect(self.on_show_peers)
        view_menu.addSeparator()
        settings_action = view_menu.addAction("Settings...")
        settings_action.triggered.connect(lambda: self._switch_page(1))
        event_log_action = view_menu.addAction("Event Log...")
        event_log_action.triggered.connect(lambda: self._switch_page(2))

        main_layout.addWidget(menu_bar)

        self.stacked_widget = QStackedWidget()

        main_page = self._build_main_page()
        self.stacked_widget.addWidget(main_page)

        settings_page = self._build_settings_page()
        self.stacked_widget.addWidget(settings_page)

        event_log_page = self._build_event_log_page()
        self.stacked_widget.addWidget(event_log_page)

        main_layout.addWidget(self.stacked_widget)
        self.setLayout(main_layout)

    def _build_main_page(self) -> QWidget:
        """Build the main call interface page."""
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready to connect")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label, 1)

        self.connection_label = QLabel("RNS: Connecting...")
        self.connection_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.connection_label.setToolTip("Reticulum Network Stack connection status")
        self.connection_label.setStyleSheet("""
            padding: 6px 12px;
            border-radius: 12px;
            font-weight: 500;
        """)
        status_layout.addWidget(self.connection_label)
        layout.addLayout(status_layout)

        colors = get_theme_colors()
        
        self.security_label = QLabel("Security: Not Connected")
        self.security_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.security_label.setStyleSheet(f"""
            border: 2px solid {colors['border']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)
        layout.addWidget(self.security_label)

        self.remote_banner = QLabel("Remote: Not Connected")
        self.remote_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.remote_banner.setStyleSheet(f"""
            border: 2px solid {colors['border']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)
        layout.addWidget(self.remote_banner)

        local_group = QGroupBox("Local Identity")
        local_layout = QVBoxLayout()
        self.local_id_label = QLabel(f"Node ID: {self.local_id}")
        self.local_id_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        local_layout.addWidget(self.local_id_label)

        local_group.setLayout(local_layout)
        layout.addWidget(local_group)

        dest_layout = QHBoxLayout()
        dest_label = QLabel("Remote ID:")
        self.remote_id_input = QLineEdit()
        self.remote_id_input.setPlaceholderText("Enter 32-byte hex identity hash")
        if self.config.last_remote_id:
            self.remote_id_input.setText(self.config.last_remote_id)
        dest_layout.addWidget(dest_label)
        dest_layout.addWidget(self.remote_id_input)
        layout.addLayout(dest_layout)

        codec_layout = QHBoxLayout()
        codec_layout.addWidget(QLabel("Call Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Ultra Low Bandwidth", Profiles.BANDWIDTH_ULTRA_LOW)
        self.profile_combo.addItem("Very Low Bandwidth", Profiles.BANDWIDTH_VERY_LOW)
        self.profile_combo.addItem("Low Bandwidth", Profiles.BANDWIDTH_LOW)
        self.profile_combo.addItem("Medium Quality (Default)", Profiles.QUALITY_MEDIUM)
        self.profile_combo.addItem("High Quality", Profiles.QUALITY_HIGH)
        self.profile_combo.addItem("Max Quality", Profiles.QUALITY_MAX)
        self.profile_combo.addItem("Low Latency", Profiles.LATENCY_LOW)
        self.profile_combo.addItem("Ultra Low Latency", Profiles.LATENCY_ULTRA_LOW)
        self.profile_combo.setCurrentIndex(3)  # Default to Medium Quality
        codec_layout.addWidget(self.profile_combo)
        layout.addLayout(codec_layout)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.call_button = QPushButton("Call")
        self.call_button.setObjectName("callButton")
        self.call_button.clicked.connect(self.on_call_clicked)
        self.call_button.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(self.call_button)

        self.hangup_button = QPushButton("Hang Up")
        self.hangup_button.setObjectName("hangupButton")
        self.hangup_button.clicked.connect(self.on_hangup_clicked)
        self.hangup_button.setEnabled(False)
        self.hangup_button.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(self.hangup_button)

        self.answer_button = QPushButton("Answer")
        self.answer_button.setObjectName("answerButton")
        self.answer_button.clicked.connect(self.on_answer_clicked)
        self.answer_button.setEnabled(False)
        self.answer_button.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(self.answer_button)

        self.reject_button = QPushButton("Reject")
        self.reject_button.setObjectName("rejectButton")
        self.reject_button.clicked.connect(self.on_reject_clicked)
        self.reject_button.setEnabled(False)
        self.reject_button.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(self.reject_button)

        self.verify_button = QPushButton("Verify Security")
        self.verify_button.setObjectName("verifyButton")
        self.verify_button.setToolTip("Verify SAS code to confirm peer identity")
        self.verify_button.clicked.connect(self.on_verify_security_clicked)
        self.verify_button.setEnabled(False)
        self.verify_button.setCursor(Qt.PointingHandCursor)
        btn_layout.addWidget(self.verify_button)

        layout.addLayout(btn_layout)

        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(10)
        
        self.announce_button = QPushButton("Announce")
        self.announce_button.clicked.connect(self.on_announce_clicked)
        self.announce_button.setCursor(Qt.PointingHandCursor)
        self.announce_button.setToolTip("Broadcast your presence to the network")
        nav_layout.addWidget(self.announce_button)

        self.peers_button = QPushButton("Discovered Peers")
        self.peers_button.clicked.connect(self.on_show_peers)
        self.peers_button.setCursor(Qt.PointingHandCursor)
        self.peers_button.setToolTip("View all discovered peers")
        nav_layout.addWidget(self.peers_button)

        self.history_button = QPushButton("Call History")
        self.history_button.clicked.connect(self.on_show_history)
        self.history_button.setCursor(Qt.PointingHandCursor)
        self.history_button.setToolTip("View your call history")
        nav_layout.addWidget(self.history_button)

        nav_layout.addStretch()
        layout.addLayout(nav_layout)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def _build_settings_page(self) -> QWidget:
        """Build the settings page."""
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Settings")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        # Display Name section
        identity_group = QGroupBox("Identity")
        identity_layout = QGridLayout()
        
        identity_layout.addWidget(QLabel("Display Name:"), 0, 0)
        self.display_name_input = QLineEdit()
        self.display_name_input.setPlaceholderText("Your name (for peer discovery)")
        self.display_name_input.setText(self.config.display_name)
        identity_layout.addWidget(self.display_name_input, 0, 1)
        
        self.save_name_button = QPushButton("Save")
        self.save_name_button.clicked.connect(self.on_save_display_name)
        identity_layout.addWidget(self.save_name_button, 0, 2)
        
        colors = get_theme_colors()
        help_text = QLabel("This name will be broadcast with presence announcements")
        help_text.setStyleSheet(f"font-size: 9pt; color: {colors['fg']};")
        help_text.setWordWrap(True)
        identity_layout.addWidget(help_text, 1, 0, 1, 3)
        
        identity_group.setLayout(identity_layout)
        layout.addWidget(identity_group)

        audio_group = QGroupBox("Audio Devices")
        audio_layout = QGridLayout()

        audio_layout.addWidget(QLabel("Input Device:"), 0, 0)
        self.input_device_combo = QComboBox()
        audio_layout.addWidget(self.input_device_combo, 0, 1)

        audio_layout.addWidget(QLabel("Output Device:"), 1, 0)
        self.output_device_combo = QComboBox()
        audio_layout.addWidget(self.output_device_combo, 1, 1)

        self.refresh_devices_btn = QPushButton("Refresh Devices")
        self.refresh_devices_btn.clicked.connect(self._refresh_audio_devices)
        audio_layout.addWidget(self.refresh_devices_btn, 0, 2, 2, 1)

        audio_group.setLayout(audio_layout)
        layout.addWidget(audio_group)

        self._refresh_audio_devices()

        filter_group = QGroupBox("Audio Filters")
        filter_layout = QGridLayout()

        filter_layout.addWidget(QLabel("Enable Filters:"), 0, 0)
        self.enable_filters_checkbox = QCheckBox()
        self.enable_filters_checkbox.setChecked(self.config.use_audio_filters)
        self.enable_filters_checkbox.stateChanged.connect(
            self._on_filter_settings_changed
        )
        filter_layout.addWidget(self.enable_filters_checkbox, 0, 1)

        filter_layout.addWidget(QLabel("Filter Type:"), 1, 0)
        self.filter_type_combo = QComboBox()
        self.filter_type_combo.addItem("Voice (300-3400 Hz)", "voice")
        self.filter_type_combo.addItem("Music (80-15000 Hz)", "music")
        self.filter_type_combo.addItem("None (No filtering)", "none")
        current_type = self.config.filter_type
        index = self.filter_type_combo.findData(current_type)
        if index >= 0:
            self.filter_type_combo.setCurrentIndex(index)
        self.filter_type_combo.currentIndexChanged.connect(
            self._on_filter_settings_changed
        )
        filter_layout.addWidget(self.filter_type_combo, 1, 1)

        filter_layout.addWidget(QLabel("Automatic Gain Control:"), 2, 0)
        self.agc_checkbox = QCheckBox("Enable AGC (consistent volume)")
        self.agc_checkbox.setChecked(self.config.use_agc)
        self.agc_checkbox.stateChanged.connect(self._on_filter_settings_changed)
        filter_layout.addWidget(self.agc_checkbox, 2, 1)

        self.agc_advanced_group = QGroupBox("AGC Advanced Settings")
        agc_advanced_layout = QGridLayout()

        agc_advanced_layout.addWidget(QLabel("Target Level (dBFS):"), 0, 0)
        self.agc_target_slider = QSlider(Qt.Horizontal)
        self.agc_target_slider.setMinimum(-30)
        self.agc_target_slider.setMaximum(-3)
        audio_filters = self.config.get_section("audio_filters")
        self.agc_target_slider.setValue(int(audio_filters.get("agc_target_level", -12)))
        self.agc_target_slider.setTickPosition(QSlider.TicksBelow)
        self.agc_target_slider.setTickInterval(3)
        self.agc_target_slider.valueChanged.connect(self._on_agc_advanced_changed)
        agc_advanced_layout.addWidget(self.agc_target_slider, 0, 1)

        self.agc_target_label = QLabel(f"{self.agc_target_slider.value()} dBFS")
        agc_advanced_layout.addWidget(self.agc_target_label, 0, 2)

        agc_advanced_layout.addWidget(QLabel("Max Gain (dB):"), 1, 0)
        self.agc_gain_slider = QSlider(Qt.Horizontal)
        self.agc_gain_slider.setMinimum(0)
        self.agc_gain_slider.setMaximum(30)
        self.agc_gain_slider.setValue(int(audio_filters.get("agc_max_gain", 12)))
        self.agc_gain_slider.setTickPosition(QSlider.TicksBelow)
        self.agc_gain_slider.setTickInterval(5)
        self.agc_gain_slider.valueChanged.connect(self._on_agc_advanced_changed)
        agc_advanced_layout.addWidget(self.agc_gain_slider, 1, 1)

        self.agc_gain_label = QLabel(f"{self.agc_gain_slider.value()} dB")
        agc_advanced_layout.addWidget(self.agc_gain_label, 1, 2)

        agc_help = QLabel(
            "Target Level: How loud to make the audio (-12 dBFS is typical)\n"
            "Max Gain: Maximum amplification allowed (prevent over-boosting)"
        )
        colors = get_theme_colors()
        agc_help.setStyleSheet(f"font-size: 8pt; color: {colors['fg']};")
        agc_help.setWordWrap(True)
        agc_advanced_layout.addWidget(agc_help, 2, 0, 1, 3)

        self.agc_advanced_group.setLayout(agc_advanced_layout)
        self.agc_advanced_group.setVisible(self.config.use_agc)
        filter_layout.addWidget(self.agc_advanced_group, 3, 0, 1, 2)

        self.agc_checkbox.stateChanged.connect(
            lambda state: self.agc_advanced_group.setVisible(state == Qt.Checked)
        )

        help_label = QLabel(
            "• Voice: Optimized for speech (removes noise outside voice range)\n"
            "• Music: Wider frequency range for better audio quality\n"
            "• AGC: Automatically balances volume levels\n"
            "Note: Restart required to apply filter changes"
        )
        colors = get_theme_colors()
        help_label.setStyleSheet(f"font-size: 9pt; color: {colors['fg']};")
        help_label.setWordWrap(True)
        filter_layout.addWidget(help_label, 4, 0, 1, 2)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        back_btn = QPushButton("← Back to Main")
        back_btn.clicked.connect(lambda: self._switch_page(0))
        layout.addWidget(back_btn)

        layout.addStretch()
        page.setLayout(layout)
        return page

    def _build_event_log_page(self) -> QWidget:
        """Build the event log page."""
        page = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel("Event Log")
        title.setObjectName("titleLabel")
        layout.addWidget(title)

        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumBlockCount(1000)  # Limit to last 1000 events
        layout.addWidget(self.event_log)

        btn_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(lambda: self.event_log.clear())
        btn_layout.addWidget(clear_btn)

        back_btn = QPushButton("← Back to Main")
        back_btn.clicked.connect(lambda: self._switch_page(0))
        btn_layout.addWidget(back_btn)

        layout.addLayout(btn_layout)
        page.setLayout(layout)
        return page

    def _switch_page(self, page_index: int) -> None:
        """Switch to a different page."""
        self.stacked_widget.setCurrentIndex(page_index)

    def _refresh_audio_devices(self) -> None:
        """Query and populate audio device lists with detailed information."""
        self.input_device_combo.setEnabled(False)
        self.output_device_combo.setEnabled(False)
        self.refresh_devices_btn.setEnabled(False)
        self.refresh_devices_btn.setText("Loading...")

        try:
            from LXST.Primitives.Telephony import Telephone

            inputs = Telephone.available_inputs()
            outputs = Telephone.available_outputs()

            if not isinstance(inputs, list):
                inputs = list(inputs) if hasattr(inputs, "__iter__") else []
            if not isinstance(outputs, list):
                outputs = list(outputs) if hasattr(outputs, "__iter__") else []

            self.input_device_combo.clear()
            self.output_device_combo.clear()

            self.input_device_combo.addItem("System Default (Recommended)", None)
            self.output_device_combo.addItem("System Default (Recommended)", None)

            for idx, device in enumerate(inputs):
                name = str(device) if not isinstance(device, str) else device
                display_name = name if len(name) <= 50 else name[:47] + "..."
                icon = "🎤" if "mic" in name.lower() or "input" in name.lower() else "🎙️"
                self.input_device_combo.addItem(f"{icon} [{idx}] {display_name}", idx)

            for idx, device in enumerate(outputs):
                name = str(device) if not isinstance(device, str) else device
                display_name = name if len(name) <= 50 else name[:47] + "..."
                icon = (
                    "🔊"
                    if "speaker" in name.lower() or "output" in name.lower()
                    else "🎧"
                )
                self.output_device_combo.addItem(f"{icon} [{idx}] {display_name}", idx)

            logger.info(
                f"Found {len(inputs)} input device(s) and {len(outputs)} output device(s)"
            )
            self.append_event(
                f"Audio devices refreshed: {len(inputs)} inputs, {len(outputs)} outputs"
            )

        except Exception as exc:
            logger.error(f"Failed to enumerate audio devices: {exc}")
            self.input_device_combo.addItem("❌ Error loading devices", None)
            self.output_device_combo.addItem("❌ Error loading devices", None)

        self.input_device_combo.setEnabled(True)
        self.output_device_combo.setEnabled(True)
        self.refresh_devices_btn.setEnabled(True)
        self.refresh_devices_btn.setText("Refresh Devices")

    def _on_filter_settings_changed(self) -> None:
        """Handle changes to audio filter settings."""
        try:
            self.config.use_audio_filters = self.enable_filters_checkbox.isChecked()
            self.config.filter_type = self.filter_type_combo.currentData()
            self.config.use_agc = self.agc_checkbox.isChecked()
            self.config.save()

            logger.info(
                f"Audio filter settings updated: filters={self.config.use_audio_filters}, "
                f"type={self.config.filter_type}, agc={self.config.use_agc}"
            )

            self.append_event(
                "Audio filter settings updated. Restart application to apply changes."
            )

        except Exception as exc:
            logger.error(f"Failed to update filter settings: {exc}")
            QMessageBox.warning(
                self, "Settings Error", f"Failed to save filter settings: {exc}"
            )

    def _on_agc_advanced_changed(self) -> None:
        """Handle changes to AGC advanced parameters."""
        try:
            self.agc_target_label.setText(f"{self.agc_target_slider.value()} dBFS")
            self.agc_gain_label.setText(f"{self.agc_gain_slider.value()} dB")

            self.config.set(
                "audio_filters",
                "agc_target_level",
                float(self.agc_target_slider.value()),
            )
            self.config.set(
                "audio_filters", "agc_max_gain", float(self.agc_gain_slider.value())
            )
            self.config.save()

            logger.info(
                f"AGC advanced settings updated: target={self.agc_target_slider.value()}, "
                f"max_gain={self.agc_gain_slider.value()}"
            )

            self.append_event(
                f"AGC settings: target {self.agc_target_slider.value()} dBFS, "
                f"max gain {self.agc_gain_slider.value()} dB"
            )

        except Exception as exc:
            logger.error(f"Failed to update AGC advanced settings: {exc}")
            QMessageBox.warning(
                self, "Settings Error", f"Failed to save AGC settings: {exc}"
            )

    def _on_recording_settings_changed(self) -> None:
        """Handle changes to recording settings."""
        try:
            self.config.set(
                "recording_enabled", self.enable_recording_checkbox.isChecked()
            )
            self.config.set("auto_record", self.auto_record_checkbox.isChecked())
            self.config.save()

            logger.info(
                f"Recording settings updated: enabled={self.config.recording_enabled}, "
                f"auto_record={self.config.auto_record}"
            )

            self.append_event("Recording settings updated.")

        except Exception as exc:
            logger.error(f"Failed to update recording settings: {exc}")
            QMessageBox.warning(
                self, "Settings Error", f"Failed to save recording settings: {exc}"
            )

    def _update_connection_status(self) -> None:
        """Update the RNS connection status indicator."""
        colors = get_theme_colors()
        if self.telephone and self.telephone.telephone:
            self.connection_label.setText("RNS: Connected")
            self.connection_label.setStyleSheet(f"""
                background-color: {colors['success']};
                color: white;
                padding: 6px 12px;
                border-radius: 12px;
                font-weight: bold;
            """)
        else:
            self.connection_label.setText("RNS: Connecting...")
            self.connection_label.setStyleSheet(f"""
                background-color: {colors['border']};
                color: white;
                padding: 6px 12px;
                border-radius: 12px;
                font-weight: 500;
            """)

    def _update_call_timer(self) -> None:
        """Update the call timer display."""
        if self._call_start_time:
            elapsed = int(time.time() - self._call_start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60

            peer_info = ""
            if hasattr(self, "_active_call_peer"):
                peer = self.peers_storage.get(self._active_call_peer)
                if peer and peer.display_name:
                    peer_info = peer.display_name
                else:
                    peer_info = self._active_call_peer[:16]

            colors = get_theme_colors()
            self.status_label.setText(
                f"In call with {peer_info} - {minutes:02d}:{seconds:02d}"
            )
            self.status_label.setStyleSheet(f"""
                background-color: {colors['success']};
                color: white;
                padding: 10px 15px;
                border-radius: 8px;
                border-left: 4px solid {colors['primary']};
                font-weight: bold;
            """)

    def append_event(self, message: str) -> None:
        """Append an event to the event log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        event = f"[{timestamp}] {message}"
        self._event_history.append(event)
        if hasattr(self, "event_log"):
            self.event_log.appendPlainText(event)

    @Slot()
    def on_announce_clicked(self) -> None:
        """Manually announce LXST telephony and LXMF presence."""
        self.telephone.announce()

        if self.lxmf_announcer:
            self.lxmf_announcer.announce()
            self.status_label.setText("Announced LXST + LXMF presence")
        else:
            self.status_label.setText("Announced LXST telephony")

        self.append_event("Manual announce sent")
        logger.info("Manual announce sent (LXST + LXMF)")
        QTimer.singleShot(3000, lambda: self.status_label.setText("Ready"))

    @Slot()
    def on_save_display_name(self) -> None:
        """Save display name and announce."""
        new_name = self.display_name_input.text().strip()

        self.config.display_name = new_name
        self.config.save()

        if self.lxmf_announcer:
            self.lxmf_announcer.display_name = new_name
            logger.info(f"Display name saved and announced: {new_name}")
            self.status_label.setText(f"Name saved: {new_name or 'Default'}")
            self.append_event(f"Display name set to: {new_name or '(empty)'}")
            QTimer.singleShot(3000, lambda: self.status_label.setText("Ready"))

    @Slot()
    def on_show_peers(self) -> None:
        """Show discovered peers window."""
        from lxst_phone.ui.peers_window import PeersWindow

        if not hasattr(self, "_peers_window"):
            self._peers_window = PeersWindow(self.peers_storage, parent=None)
            self._peers_window.peerSelected.connect(self._on_peer_selected)

        self._peers_window.show()
        self._peers_window.raise_()
        self._peers_window.activateWindow()

    @Slot(str)
    def _on_peer_selected(self, node_id: str) -> None:
        """Handle peer selection."""
        self.remote_id_input.setText(node_id)
        self.append_event(f"Selected peer from list: {node_id[:16]}...")
        logger.info(f"Selected peer: {node_id[:16]}...")

    @Slot()
    def on_show_history(self) -> None:
        """Show call history window."""
        from lxst_phone.ui.call_history_window import CallHistoryWindow

        history_window = CallHistoryWindow(self.call_history, self)
        history_window.callRequested.connect(self._on_call_from_history)
        history_window.exec()

    @Slot(str)
    def _on_call_from_history(self, peer_id: str) -> None:
        """Handle call request from history."""
        self.remote_id_input.setText(peer_id)
        self.append_event(f"Selected from history: {peer_id[:16]}...")
        logger.info(f"Selected from history: {peer_id[:16]}...")

    @Slot()
    def on_export_identity(self) -> None:
        """Export identity to an encrypted backup file."""
        from lxst_phone.identity import get_identity_storage_path

        identity_path = get_identity_storage_path()
        QMessageBox.information(
            self,
            "Manual Backup",
            "Identity export/import functionality is not yet implemented.\n\n"
            "To backup your identity, copy this file:\n"
            f"{identity_path}\n\n"
            "Keep it safe - you'll need it to restore your identity!",
        )

    @Slot()
    def on_import_identity(self) -> None:
        """Import identity from an encrypted backup file."""
        from lxst_phone.identity import get_identity_storage_path

        identity_path = get_identity_storage_path()
        QMessageBox.information(
            self,
            "Manual Import",
            "Identity export/import functionality is not yet implemented.\n\n"
            "To manually import an identity:\n"
            "1. Backup your current identity file (if any)\n"
            "2. Replace this file with your backup:\n"
            f"{identity_path}\n"
            "3. Restart the application",
        )

    @Slot()
    def on_call_clicked(self) -> None:
        """User clicked Call button."""
        remote_id_hex = self.remote_id_input.text().strip()

        if not remote_id_hex:
            QMessageBox.warning(self, "Error", "Please enter a remote ID")
            return

        try:
            peer = self.peers_storage.get(remote_id_hex)

            if peer:
                identity_hash_hex = peer.node_id
                identity_hash_bytes = bytes.fromhex(identity_hash_hex)
                logger.debug(
                    f"Calling peer: {peer.display_name} ({identity_hash_hex[:16]}...)"
                )
            else:
                identity_hash_hex = remote_id_hex
                identity_hash_bytes = bytes.fromhex(identity_hash_hex)
                logger.debug(f"Calling identity hash: {identity_hash_hex[:16]}...")

            lxmf_dest_hash = RNS.Destination.hash_from_name_and_identity(
                "lxmf.delivery", identity_hash_bytes
            )

            remote_identity = RNS.Identity.recall(lxmf_dest_hash)

            if not remote_identity:
                if peer and peer.destination_hash:
                    lxst_dest_bytes = bytes.fromhex(peer.destination_hash)
                    remote_identity = RNS.Identity.recall(lxst_dest_bytes)
                    logger.debug(
                        f"Recalled from stored LXST dest: {peer.destination_hash[:16]}..."
                    )

            if not remote_identity:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Could not recall identity. Make sure the remote peer has announced.",
                )
                return

            lxst_dest_hash = RNS.Destination.hash_from_name_and_identity(
                "lxst.telephony", remote_identity
            )

            if not RNS.Transport.has_path(lxst_dest_hash):
                logger.info(f"No path to LXST destination, requesting...")
                RNS.Transport.request_path(lxst_dest_hash)
                self.status_label.setText("Requesting path...")
                self.append_event(f"Requesting path to {remote_id_hex[:16]}...")
                QMessageBox.information(
                    self,
                    "Path Request",
                    "No path to destination. Path has been requested. Please try again in a moment.",
                )
                return

            if peer and not peer.verified:
                logger.info(f"Calling unverified peer, showing warning...")
                if not warn_unverified_peer(identity_hash_hex, self):
                    logger.info("User cancelled call to unverified peer")
                    return

            profile = self.profile_combo.currentData()

            logger.info(f"Initiating call to {identity_hash_hex}...")
            self.append_event(f"Calling {remote_id_hex[:16]}...")
            self.telephone.call(remote_identity, profile=profile)

            self.config.last_remote_id = remote_id_hex
            self.config.save()

            display_name = peer.display_name if peer else remote_id_hex[:16]
            self.status_label.setText(f"Calling {display_name}...")
            self.remote_banner.setText(f"Remote: Calling {display_name}...")
            self.call_button.setEnabled(False)
            self.hangup_button.setEnabled(True)

        except ValueError:
            QMessageBox.warning(self, "Error", "Invalid identity hash format")
        except Exception as exc:
            logger.error(f"Failed to initiate call: {exc}")
            QMessageBox.critical(self, "Error", f"Failed to initiate call: {exc}")

    @Slot()
    def on_hangup_clicked(self) -> None:
        """User clicked Hang Up button."""
        logger.info("Hanging up")
        self.append_event("Hanging up call")
        self.telephone.hangup()

    @Slot()
    def on_answer_clicked(self) -> None:
        """User clicked Answer button."""
        if hasattr(self, "_incoming_identity"):
            logger.info("Answering call")
            self.append_event("Answering incoming call")
            self.telephone.answer(self._incoming_identity)
            self.answer_button.setEnabled(False)
            self.reject_button.setEnabled(False)
            self.hangup_button.setEnabled(True)

    @Slot()
    def on_reject_clicked(self) -> None:
        """User clicked Reject button."""
        if hasattr(self, "_incoming_identity"):
            logger.info("Rejecting call")
            self.append_event("Rejecting incoming call")
            self.telephone.reject(self._incoming_identity)
            self.answer_button.setEnabled(False)
            self.reject_button.setEnabled(False)

    @Slot(object, str)
    def on_call_ringing(self, identity: RNS.Identity, identity_hash: str) -> None:
        """Incoming call is ringing."""
        logger.info(f"Incoming call from {identity_hash}...")

        if self.peers_storage.is_blocked(identity_hash):
            logger.warning(
                f"Auto-rejecting call from blocked peer: {identity_hash[:16]}..."
            )
            self.telephone.reject(identity)
            self.status_label.setText("Blocked caller rejected")
            self.append_event(f"Auto-rejected blocked caller: {identity_hash[:16]}...")
            QTimer.singleShot(3000, lambda: self.status_label.setText("Ready"))
            return

        self._incoming_identity = identity

        peer = self.peers_storage.get(identity_hash)
        display_name = peer.display_name if peer else identity_hash[:16]

        self.status_label.setText(f"Incoming call from {display_name}...")
        self.remote_banner.setText(f"Remote: Incoming from {display_name}")
        self.append_event(f"Incoming call from {display_name}")

        self.answer_button.setEnabled(True)
        self.reject_button.setEnabled(True)
        self.call_button.setEnabled(False)

    @Slot(str)
    def on_call_established(self, identity_hash: str) -> None:
        """Call has been established."""
        logger.info(f"Call established with {identity_hash}...")

        self._call_start_time = time.time()
        self._active_call_peer = identity_hash

        peer = self.peers_storage.get(identity_hash)
        display_name = peer.display_name if peer else identity_hash[:16]

        colors = get_theme_colors()
        self.status_label.setText(f"In call with {display_name}")
        self.status_label.setStyleSheet(f"""
            background-color: {colors['success']};
            color: white;
            padding: 10px 15px;
            border-radius: 8px;
            border-left: 4px solid {colors['primary']};
            font-weight: bold;
        """)
        self.remote_banner.setText(f"Remote: Connected to {display_name}")
        self.remote_banner.setStyleSheet(f"""
            border: 2px solid {colors['success']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['card_bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)
        self.security_label.setText("Security: Encrypted (verify SAS to confirm)")
        self.security_label.setStyleSheet(f"""
            border: 2px solid {colors['warning']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['card_bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)
        self.append_event(f"Call established with {display_name}")

        self.hangup_button.setEnabled(True)
        self.call_button.setEnabled(False)
        self.answer_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        self.verify_button.setEnabled(True)

        self.call_timer.start()

    @Slot(str)
    def on_call_ended(self, identity_hash: str) -> None:
        """Call has ended."""
        logger.info(f"Call ended")

        self.call_timer.stop()

        if hasattr(self, "_call_start_time") and self._call_start_time:
            duration = int(time.time() - self._call_start_time)

            direction = (
                "outgoing" if not hasattr(self, "_incoming_identity") else "incoming"
            )
            peer_id = (
                identity_hash if identity_hash else self.remote_id_input.text().strip()
            )

            if peer_id:
                import hashlib

                call_id = hashlib.sha256(
                    f"{self._call_start_time}:{peer_id}:{direction}".encode()
                ).hexdigest()[:16]

                self.call_history.add_call(
                    direction=direction,
                    peer_id=peer_id,
                    display_name="Unknown",
                    duration_sec=duration,
                    answered=True,
                    call_id=call_id,
                )

            self.append_event(f"Call ended (duration: {duration}s)")
            self._call_start_time = None

        colors = get_theme_colors()
        self.status_label.setText("Ready to connect")
        self.status_label.setStyleSheet(f"""
            background-color: {colors['card_bg']};
            color: {colors['fg']};
            padding: 10px 15px;
            border-radius: 8px;
            border-left: 4px solid {colors['info']};
        """)
        self.remote_banner.setText("Remote: Not Connected")
        self.remote_banner.setStyleSheet(f"""
            border: 2px solid {colors['border']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)
        self.security_label.setText("Security: Not Connected")
        self.security_label.setStyleSheet(f"""
            border: 2px solid {colors['border']};
            padding: 8px 12px;
            border-radius: 6px;
            font-family: monospace;
            background-color: {colors['bg']};
            color: {colors['fg']};
            font-weight: 500;
        """)

        self.call_button.setEnabled(True)
        self.hangup_button.setEnabled(False)
        self.answer_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        self.verify_button.setEnabled(False)

        if hasattr(self, "_incoming_identity"):
            delattr(self, "_incoming_identity")
        if hasattr(self, "_active_call_peer"):
            delattr(self, "_active_call_peer")

    @Slot(str)
    def on_call_busy(self, identity_hash: str) -> None:
        """Remote peer is busy."""
        logger.info(f"Peer busy: {identity_hash[:16]}...")

        self.status_label.setText(f"Peer busy")
        self.remote_banner.setText("Remote: [Busy]")
        self.append_event(f"Call failed: peer busy")
        QMessageBox.information(self, "Call Failed", "The remote peer is busy")

        self.call_button.setEnabled(True)
        self.hangup_button.setEnabled(False)
        self.verify_button.setEnabled(False)

    @Slot(str)
    def on_call_rejected(self, identity_hash: str) -> None:
        """Call was rejected."""
        logger.info(f"Call rejected by {identity_hash[:16]}...")

        self.status_label.setText("Call rejected")
        self.remote_banner.setText("Remote: [Rejected]")
        self.append_event(f"Call rejected by peer")
        QMessageBox.information(self, "Call Rejected", "The call was rejected")

        self.call_button.setEnabled(True)
        self.hangup_button.setEnabled(False)
        self.verify_button.setEnabled(False)

    @Slot()
    def on_verify_security_clicked(self) -> None:
        """User clicked Verify Security button to check SAS code."""
        if not hasattr(self, "_active_call_peer"):
            logger.warning("Verify Security clicked but no active call")
            return

        peer_id = self._active_call_peer
        logger.info(f"Verifying security for call with {peer_id[:16]}...")

        sas_code = self.telephone.get_sas_code()
        if not sas_code:
            QMessageBox.warning(
                self,
                "SAS Unavailable",
                "Unable to retrieve security code. The call may not be fully established.",
            )
            return

        peer = self.peers_storage.get(peer_id)
        display_name = peer.display_name if peer else peer_id[:16]

        verified = show_sas_verification(sas_code, display_name, self)

        if verified:
            logger.info(f"SAS verified for peer {peer_id[:16]}...")
            colors = get_theme_colors()
            self.peers_storage.mark_verified(peer_id)
            self.peers_storage.save()
            self.security_label.setText("Security: Encrypted & Verified")
            self.security_label.setStyleSheet(f"""
                border: 2px solid {colors['verified']};
                padding: 8px 12px;
                border-radius: 6px;
                font-family: monospace;
                background-color: {colors['card_bg']};
                font-weight: bold;
                color: {colors['verified']};
            """)
            self.status_label.setText("Security verified!")
            self.status_label.setStyleSheet(f"""
                background-color: {colors['verified']};
                color: white;
                padding: 10px 15px;
                border-radius: 8px;
                border-left: 4px solid {colors['primary']};
                font-weight: bold;
            """)
            self.append_event(f"SAS verified for {display_name}")
            QTimer.singleShot(2000, lambda: self._update_call_timer())
        else:
            logger.info(f"SAS verification cancelled or failed for {peer_id[:16]}...")
            self.append_event(f"SAS verification cancelled")

    @Slot(str, str, str)
    def on_lxmf_peer_discovered(
        self, identity_hash: str, display_name: str, lxst_dest_hash: str
    ) -> None:
        """Handle discovery of LXMF peer (Sideband/MeshChat) with display name."""
        logger.debug(
            f"LXMF peer discovered: {display_name} ({identity_hash[:16]}..., LXST dest: {lxst_dest_hash[:16]}...)"
        )

        self.peers_storage.add_or_update(identity_hash, display_name, lxst_dest_hash)
        self.peers_storage.save()

        if hasattr(self, "_peers_window") and self._peers_window:
            self._peers_window._refresh_list()

        self.status_label.setText(f"Discovered: {display_name}")
        self.append_event(f"Discovered peer: {display_name}")
        QTimer.singleShot(3000, lambda: self.status_label.setText("Ready"))

    def closeEvent(self, event):
        """Handle window close event."""
        self.config.window_geometry = (self.width(), self.height())
        self.config.save()

        if hasattr(self, "_peers_window") and self._peers_window:
            self._peers_window.close()

        event.accept()
