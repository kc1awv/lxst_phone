import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, Slot, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QPlainTextEdit,
    QGroupBox,
    QProgressBar,
    QGridLayout,
    QComboBox,
    QStackedWidget,
    QMenuBar,
    QFileDialog,
    QInputDialog,
)

from lxst_phone.logging_config import get_logger
from lxst_phone.core.call_state import CallStateMachine, CallPhase, CallInfo
from lxst_phone.core.signaling import (
    CallMessage,
    build_accept,
    build_end,
    build_invite,
    build_reject,
    negotiate_codec,
    new_call_id,
)
from lxst_phone.core.reticulum_client import ReticulumClient
from lxst_phone.ui.security_dialogs import (
    show_sas_verification,
    warn_unverified_peer,
    warn_unencrypted_connection,
)

logger = get_logger("ui")
from lxst_phone.core.message_filter import CallMessageFilter
from lxst_phone.core import media
from lxst_phone.config import Config
from lxst_phone.ui.peers_window import PeersWindow
from lxst_phone.peers_storage import PeersStorage


class MainWindow(QWidget):
    incomingCallMessage = Signal(object)

    def __init__(
        self,
        call_state: CallStateMachine,
        local_id: str,
        reticulum_client: ReticulumClient,
        audio_input_device: int | None = None,
        audio_output_device: int | None = None,
        audio_enabled: bool = True,
        config: Config | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.call_state = call_state
        self.local_id = local_id
        self.reticulum_client = reticulum_client
        self.audio_input_device = audio_input_device
        self.audio_output_device = audio_output_device
        self.audio_enabled = audio_enabled
        self.config = config if config is not None else Config()
        self.media_active = False
        self._event_history: list[str] = []
        self.msg_filter = CallMessageFilter(local_id, dupe_window_sec=1.0)

        self.peers_storage = PeersStorage()
        self.peers_storage.load()

        self.peers_window = PeersWindow(self.peers_storage)
        self.peers_window.peerSelected.connect(self._on_peer_selected)

        from lxst_phone.call_history import CallHistory

        self.call_history = CallHistory(identity=reticulum_client.node_identity)
        self.call_history.load()

        from lxst_phone.rate_limiter import RateLimiter

        self.rate_limiter = RateLimiter(
            max_calls_per_minute=config.max_calls_per_minute,
            max_calls_per_hour=config.max_calls_per_hour,
        )

        from lxst_phone.ringtone import RingtonePlayer, get_ringtone_paths

        incoming_path, outgoing_path = get_ringtone_paths(
            config.ringtone_incoming, config.ringtone_outgoing
        )
        self.ringtone_player = RingtonePlayer(
            incoming_ringtone_path=incoming_path,
            outgoing_ringtone_path=outgoing_path,
            enabled=config.ringtone_enabled,
        )

        self._call_start_time: float | None = None

        peer_count = self.peers_window.get_peer_count()
        if peer_count > 0:
            self._initial_peer_count = peer_count
        else:
            self._initial_peer_count = 0

        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self._update_stats_display)
        self.stats_timer.setInterval(200)  # Update 5 times per second

        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self._update_connection_status)
        self.connection_timer.setInterval(2000)  # Update every 2 seconds
        self.connection_timer.start()

        self.setWindowTitle("LXST Phone (Prototype)")

        w, h = self.config.window_geometry
        self.resize(w, h)

        self._build_ui()

        self._update_connection_status()

        self.call_state.on_state_changed = self.on_call_state_changed
        self.incomingCallMessage.connect(self.handle_incoming_call_message)

    def _build_ui(self) -> None:
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
        history_action.triggered.connect(self.on_view_call_history)

        main_layout.addWidget(menu_bar)

        content_widget = QWidget()
        layout = QVBoxLayout()
        content_widget.setLayout(layout)
        main_layout.addWidget(content_widget)

        self.setLayout(main_layout)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Status: Idle")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        status_layout.addWidget(self.status_label, 1)  # Stretch factor 1

        self.connection_label = QLabel("⚫ RNS: Connecting...")
        self.connection_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.connection_label.setToolTip("Reticulum Network Stack connection status")
        status_layout.addWidget(self.connection_label)

        layout.addLayout(status_layout)

        security_layout = QHBoxLayout()
        self.security_label = QLabel("Security: [Not Connected]")
        self.security_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.security_label.setStyleSheet(
            "QLabel { border: 1px solid palette(mid); padding: 4px; font-family: monospace; }"
        )
        security_layout.addWidget(self.security_label)

        self.verify_sas_btn = QPushButton("Verify Security")
        self.verify_sas_btn.setToolTip("Verify the security code with the other person")
        self.verify_sas_btn.setEnabled(False)
        self.verify_sas_btn.clicked.connect(self.on_verify_sas_clicked)
        security_layout.addWidget(self.verify_sas_btn)

        layout.addLayout(security_layout)

        self.remote_banner = QLabel("Remote: [Not Connected]")
        self.remote_banner.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.remote_banner.setStyleSheet(
            "QLabel { border: 1px solid palette(mid); padding: 4px; font-family: monospace; }"
        )
        layout.addWidget(self.remote_banner)

        self.local_id_label = QLabel(f"Local node ID (hex):\n{self.local_id}")
        self.local_id_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.local_id_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        layout.addWidget(self.local_id_label)

        dest_layout = QHBoxLayout()
        dest_label = QLabel("Remote node ID:")
        self.dest_input = QLineEdit()
        self.dest_input.setPlaceholderText("Paste remote node ID here")
        if self.config.last_remote_id:
            self.dest_input.setText(self.config.last_remote_id)
        dest_layout.addWidget(dest_label)
        dest_layout.addWidget(self.dest_input)
        layout.addLayout(dest_layout)

        btn_layout = QHBoxLayout()
        self.call_btn = QPushButton("Call")
        self.end_btn = QPushButton("End")
        self.end_btn.setEnabled(False)
        self.accept_btn = QPushButton("Accept")
        self.reject_btn = QPushButton("Reject")
        self.accept_btn.setEnabled(False)
        self.reject_btn.setEnabled(False)
        self.reset_btn = QPushButton("Reset to Idle")
        self.reset_btn.setToolTip("Force-reset UI and state machine back to idle.")
        self.simulate_invite_btn = QPushButton("Simulate Incoming")
        self.simulate_invite_btn.setToolTip(
            "Dev helper: generate a fake incoming invite for UI testing.\n"
            "Note: Audio will not work in simulated calls (no real RNS link)."
        )
        self.announce_btn = QPushButton("Announce")
        self.announce_btn.setToolTip("Send a presence announcement for peer discovery")

        self.call_btn.clicked.connect(self.on_call_clicked)
        self.end_btn.clicked.connect(self.on_end_clicked)
        self.accept_btn.clicked.connect(self.on_accept_clicked)
        self.reject_btn.clicked.connect(self.on_reject_clicked)
        self.announce_btn.clicked.connect(self.on_announce_clicked)
        self.reset_btn.clicked.connect(self.on_reset_clicked)
        self.simulate_invite_btn.clicked.connect(self.on_simulate_incoming_clicked)

        btn_layout.addWidget(self.call_btn)
        btn_layout.addWidget(self.end_btn)
        btn_layout.addWidget(self.announce_btn)
        btn_layout.addWidget(self.accept_btn)
        btn_layout.addWidget(self.reject_btn)
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.simulate_invite_btn)
        layout.addLayout(btn_layout)

        self._build_stats_panel(layout)

        nav_layout = QHBoxLayout()
        self.view_event_log_btn = QPushButton("View Event Log")
        self.view_event_log_btn.clicked.connect(lambda: self._switch_page(1))
        nav_layout.addWidget(self.view_event_log_btn)

        self.view_audio_settings_btn = QPushButton("Settings")
        self.view_audio_settings_btn.clicked.connect(lambda: self._switch_page(2))
        nav_layout.addWidget(self.view_audio_settings_btn)

        self.view_peers_btn = QPushButton("Discovered Peers")
        self.view_peers_btn.clicked.connect(self._on_show_peers_window)
        nav_layout.addWidget(self.view_peers_btn)

        if self._initial_peer_count > 0:
            self.view_peers_btn.setText(
                f"Discovered Peers ({self._initial_peer_count})"
            )

        self.view_history_btn = QPushButton("Call History")
        self.view_history_btn.clicked.connect(self.on_view_call_history)
        nav_layout.addWidget(self.view_history_btn)

        nav_layout.addStretch()
        layout.addLayout(nav_layout)

        self.setLayout(layout)

        self.stacked_widget = QStackedWidget()

        main_page = QWidget()
        main_page.setLayout(layout)
        self.stacked_widget.addWidget(main_page)

        self._build_event_log_page()

        self._build_audio_settings_page()

        wrapper_layout = QVBoxLayout()
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addWidget(self.stacked_widget)

        QWidget().setLayout(self.layout())
        self.setLayout(wrapper_layout)

    def _switch_page(self, page_index: int) -> None:
        """Switch to a different page in the stacked widget."""
        self.stacked_widget.setCurrentIndex(page_index)

    def _on_show_peers_window(self) -> None:
        """Show the peers window."""
        self.peers_window.show()
        self.peers_window.raise_()
        self.peers_window.activateWindow()

    def _on_peer_selected(self, node_id: str) -> None:
        """Handle peer selection from peers window."""
        self.dest_input.setText(node_id)
        self.append_event(f"Auto-filled remote ID from peer: {node_id[:16]}...")

    @Slot()
    def on_export_identity(self) -> None:
        """Export identity to an encrypted backup file."""
        from pathlib import Path
        from lxst_phone.identity_backup import export_identity

        password, ok = QInputDialog.getText(
            self,
            "Export Identity",
            "Enter a password to encrypt the backup:\n(Minimum 8 characters)",
            QLineEdit.Password,
        )

        if not ok or not password:
            return

        if len(password) < 8:
            QMessageBox.warning(
                self, "Invalid Password", "Password must be at least 8 characters long."
            )
            return

        password_confirm, ok = QInputDialog.getText(
            self, "Export Identity", "Confirm password:", QLineEdit.Password
        )

        if not ok or password != password_confirm:
            QMessageBox.warning(self, "Password Mismatch", "Passwords do not match.")
            return

        default_name = f"lxst_phone_identity_{self.local_id[:8]}.backup"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Identity",
            str(Path.home() / default_name),
            "Backup Files (*.backup);;All Files (*)",
        )

        if not file_path:
            return

        try:
            identity = self.reticulum_client.node_identity
            if not identity:
                raise ValueError("No identity available")

            export_identity(identity, Path(file_path), password)

            QMessageBox.information(
                self,
                "Export Successful",
                f"Identity exported successfully to:\n{file_path}\n\n"
                f"Node ID: {self.local_id}\n\n"
                "Keep this file and password safe!\n"
                "You will need both to restore your identity.",
            )
            logger.info(f"Identity exported to {file_path}")

        except Exception as exc:
            logger.error(f"Failed to export identity: {exc}")
            QMessageBox.critical(
                self, "Export Failed", f"Failed to export identity:\n{exc}"
            )

    @Slot()
    def on_import_identity(self) -> None:
        """Import identity from an encrypted backup file."""
        from pathlib import Path
        from lxst_phone.identity_backup import import_identity, validate_backup_file
        from lxst_phone.identity import save_identity, get_identity_storage_path

        reply = QMessageBox.question(
            self,
            "Import Identity",
            "WARNING: Importing an identity will replace your current identity.\n\n"
            f"Current Node ID: {self.local_id}\n\n"
            "Your current identity will be backed up to:\n"
            f"{get_identity_storage_path()}.backup\n\n"
            "Do you want to continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if reply != QMessageBox.Yes:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Import Identity",
            str(Path.home()),
            "Backup Files (*.backup);;All Files (*)",
        )

        if not file_path:
            return

        try:
            info = validate_backup_file(Path(file_path))
            if not info.get("valid"):
                QMessageBox.critical(
                    self,
                    "Invalid Backup",
                    f"This is not a valid LXST Phone identity backup.\n\n"
                    f"Format: {info.get('format', 'unknown')}",
                )
                return
        except Exception as exc:
            QMessageBox.critical(
                self, "Invalid Backup", f"Cannot read backup file:\n{exc}"
            )
            return

        password, ok = QInputDialog.getText(
            self, "Import Identity", "Enter the backup password:", QLineEdit.Password
        )

        if not ok or not password:
            return

        try:
            new_identity = import_identity(Path(file_path), password)
            new_node_id = new_identity.hash.hex()

            current_identity = self.reticulum_client.node_identity
            if current_identity:
                backup_path = get_identity_storage_path().with_suffix(".backup")
                save_identity(current_identity, backup_path)
                logger.info(f"Current identity backed up to {backup_path}")

            save_identity(new_identity, get_identity_storage_path())

            QMessageBox.information(
                self,
                "Import Successful",
                f"Identity imported successfully!\n\n"
                f"New Node ID: {new_node_id}\n\n"
                "You must restart the application for changes to take effect.",
            )
            logger.info(f"Identity imported from {file_path}")

            self.close()

        except ValueError as exc:
            logger.error(f"Failed to import identity: {exc}")
            QMessageBox.critical(
                self,
                "Import Failed",
                f"Failed to import identity:\n{exc}\n\n"
                "This is usually caused by an incorrect password.",
            )
        except Exception as exc:
            logger.error(f"Failed to import identity: {exc}")
            QMessageBox.critical(
                self, "Import Failed", f"Failed to import identity:\n{exc}"
            )

    @Slot()
    def on_view_call_history(self) -> None:
        """Open the call history window."""
        from lxst_phone.ui.call_history_window import CallHistoryWindow

        history_window = CallHistoryWindow(self.call_history, self)
        history_window.callRequested.connect(self._on_call_from_history)
        history_window.exec()

    def _on_call_from_history(self, peer_id: str) -> None:
        """Handle call request from call history."""
        self.dest_input.setText(peer_id)
        logger.info(f"Auto-filled remote ID from call history: {peer_id[:16]}...")

    def _build_event_log_page(self) -> None:
        """Create the full-screen event log page."""
        log_page = QWidget()
        log_layout = QVBoxLayout()

        header_layout = QHBoxLayout()
        back_btn = QPushButton("← Back to Main")
        back_btn.clicked.connect(lambda: self._switch_page(0))
        header_layout.addWidget(back_btn)
        header_layout.addStretch()
        log_layout.addLayout(header_layout)

        self.log_label = QLabel("Event Log")
        self.log_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(200)

        log_layout.addWidget(self.log_label)
        log_layout.addWidget(self.log_view)
        log_page.setLayout(log_layout)

        self.stacked_widget.addWidget(log_page)

    def _build_audio_settings_page(self) -> None:
        """Create the full-screen audio settings page."""
        audio_page = QWidget()
        audio_layout = QVBoxLayout()

        header_layout = QHBoxLayout()
        back_btn = QPushButton("← Back to Main")
        back_btn.clicked.connect(lambda: self._switch_page(0))
        header_layout.addWidget(back_btn)
        header_layout.addStretch()
        audio_layout.addLayout(header_layout)

        title_label = QLabel("Audio Settings")
        title_label.setStyleSheet("font-size: 16pt; font-weight: bold;")
        audio_layout.addWidget(title_label)

        self._build_user_settings_panel(audio_layout)

        self._build_audio_settings_panel(audio_layout)

        self._build_codec_settings_panel(audio_layout)

        audio_layout.addStretch()
        audio_page.setLayout(audio_layout)

        self.stacked_widget.addWidget(audio_page)

    def _build_user_settings_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the user settings panel."""
        user_group = QGroupBox("User Settings")
        user_layout = QGridLayout()

        user_layout.addWidget(QLabel("Display Name:"), 0, 0)
        self.display_name_input = QLineEdit()
        self.display_name_input.setPlaceholderText("Your name (shown in announcements)")
        self.display_name_input.setText(self.config.display_name)
        self.display_name_input.setMaxLength(64)  # Limit to 64 characters
        self.display_name_input.textChanged.connect(self._on_display_name_changed)
        user_layout.addWidget(self.display_name_input, 0, 1)

        info_label = QLabel(
            "This name will be sent with presence announcements so others can identify you. (Max 64 characters)"
        )
        info_label.setStyleSheet("color: gray; font-size: 9pt;")
        info_label.setWordWrap(True)
        user_layout.addWidget(info_label, 1, 0, 1, 2)

        user_group.setLayout(user_layout)
        parent_layout.addWidget(user_group)

    def _build_audio_settings_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the audio device selection panel."""
        audio_group = QGroupBox("Audio Device Selection")
        audio_layout = QGridLayout()

        audio_layout.addWidget(QLabel("Input Device:"), 0, 0)
        self.input_device_combo = QComboBox()
        self.input_device_combo.currentIndexChanged.connect(
            self._on_input_device_changed
        )
        audio_layout.addWidget(self.input_device_combo, 0, 1)

        audio_layout.addWidget(QLabel("Output Device:"), 1, 0)
        self.output_device_combo = QComboBox()
        self.output_device_combo.currentIndexChanged.connect(
            self._on_output_device_changed
        )
        audio_layout.addWidget(self.output_device_combo, 1, 1)

        self.refresh_devices_btn = QPushButton("Refresh Devices")
        self.refresh_devices_btn.clicked.connect(self._refresh_audio_devices)
        audio_layout.addWidget(self.refresh_devices_btn, 0, 2, 2, 1)

        audio_group.setLayout(audio_layout)
        parent_layout.addWidget(audio_group)

        self._refresh_audio_devices()

    def _refresh_audio_devices(self) -> None:
        """Query and populate audio device lists."""
        self.input_device_combo.setEnabled(False)
        self.output_device_combo.setEnabled(False)
        self.refresh_devices_btn.setEnabled(False)
        self.refresh_devices_btn.setText("Loading...")

        try:
            import sounddevice as sd  # type: ignore

            devices = sd.query_devices()

            self.input_device_combo.clear()
            self.output_device_combo.clear()

            self.input_device_combo.addItem("System Default", None)
            self.output_device_combo.addItem("System Default", None)

            for idx, device in enumerate(devices):
                device_name = device["name"]
                max_in = device.get("max_input_channels", 0)
                max_out = device.get("max_output_channels", 0)

                if max_in > 0:
                    display_name = f"{idx}: {device_name} ({max_in} in)"
                    self.input_device_combo.addItem(display_name, idx)

                if max_out > 0:
                    display_name = f"{idx}: {device_name} ({max_out} out)"
                    self.output_device_combo.addItem(display_name, idx)

            self._select_device_in_combo(
                self.input_device_combo, self.audio_input_device
            )
            self._select_device_in_combo(
                self.output_device_combo, self.audio_output_device
            )

        except ImportError:
            logger.warning("sounddevice not available")
            self.input_device_combo.addItem("sounddevice not installed", None)
            self.output_device_combo.addItem("sounddevice not installed", None)
        except (OSError, RuntimeError) as exc:
            logger.error(f"Audio system error: {exc}")
            self.input_device_combo.addItem("Audio system error", None)
            self.output_device_combo.addItem("Audio system error", None)
        except Exception as exc:
            logger.error(f"Unexpected error querying audio devices: {exc}")
            self.input_device_combo.addItem("Error loading devices", None)
            self.output_device_combo.addItem("Error loading devices", None)
        finally:
            self.input_device_combo.setEnabled(True)
            self.output_device_combo.setEnabled(True)
            self.refresh_devices_btn.setEnabled(True)
            self.refresh_devices_btn.setText("Refresh Devices")

    def _select_device_in_combo(self, combo: QComboBox, device_id: int | None) -> None:
        """Select the device in the combo box by its ID."""
        if device_id is None:
            combo.setCurrentIndex(0)  # System Default
            return

        for i in range(combo.count()):
            if combo.itemData(i) == device_id:
                combo.setCurrentIndex(i)
                return

    def _on_input_device_changed(self, index: int) -> None:
        """Handle input device selection change."""
        device_id = self.input_device_combo.itemData(index)
        self.audio_input_device = device_id
        self.config.audio_input_device = device_id
        logger.info(f"Input device changed to: {device_id}")

    def _on_output_device_changed(self, index: int) -> None:
        """Handle output device selection change."""
        device_id = self.output_device_combo.itemData(index)
        self.audio_output_device = device_id
        self.config.audio_output_device = device_id
        logger.info(f"Output device changed to: {device_id}")

    def _on_display_name_changed(self, text: str) -> None:
        """Handle display name change."""
        self.config.display_name = text
        self.config.save()
        logger.info(f"Display name changed to: '{text}'")

    def _build_codec_settings_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the codec settings panel."""
        codec_group = QGroupBox("Codec Settings (applies to next call)")
        codec_layout = QGridLayout()

        codec_layout.addWidget(QLabel("Codec:"), 0, 0)
        self.codec_combo = QComboBox()
        self.codec_combo.addItem("Opus (High Quality)", "opus")
        self.codec_combo.addItem("Codec2 (Low Bandwidth)", "codec2")
        codec_current = self.config.codec_type
        self.codec_combo.setCurrentIndex(0 if codec_current == "opus" else 1)
        self.codec_combo.currentIndexChanged.connect(self._on_codec_changed)
        codec_layout.addWidget(self.codec_combo, 0, 1)

        codec_layout.addWidget(QLabel("Opus Bitrate:"), 1, 0)
        self.opus_bitrate_combo = QComboBox()
        self.opus_bitrate_combo.addItem("8 kbps (Very Low)", 8000)
        self.opus_bitrate_combo.addItem("12 kbps (Low)", 12000)
        self.opus_bitrate_combo.addItem("16 kbps (Medium-Low)", 16000)
        self.opus_bitrate_combo.addItem("24 kbps (Medium - Default)", 24000)
        self.opus_bitrate_combo.addItem("32 kbps (Medium-High)", 32000)
        self.opus_bitrate_combo.addItem("48 kbps (High)", 48000)
        self.opus_bitrate_combo.addItem("64 kbps (Very High)", 64000)
        current_bitrate = self.config.opus_bitrate
        for i in range(self.opus_bitrate_combo.count()):
            if self.opus_bitrate_combo.itemData(i) == current_bitrate:
                self.opus_bitrate_combo.setCurrentIndex(i)
                break
        self.opus_bitrate_combo.currentIndexChanged.connect(
            self._on_opus_bitrate_changed
        )
        codec_layout.addWidget(self.opus_bitrate_combo, 1, 1)

        codec_layout.addWidget(QLabel("Codec2 Mode:"), 2, 0)
        self.codec2_mode_combo = QComboBox()
        self.codec2_mode_combo.addItem("3200 bps (Best Quality)", 3200)
        self.codec2_mode_combo.addItem("2400 bps (High Quality)", 2400)
        self.codec2_mode_combo.addItem("1600 bps (Medium Quality)", 1600)
        self.codec2_mode_combo.addItem("1400 bps (Low Bandwidth)", 1400)
        self.codec2_mode_combo.addItem("1300 bps (Very Low)", 1300)
        self.codec2_mode_combo.addItem("1200 bps (Minimal)", 1200)
        self.codec2_mode_combo.addItem("700C bps (Ultra Low)", 700)
        current_mode = self.config.codec2_mode
        for i in range(self.codec2_mode_combo.count()):
            if self.codec2_mode_combo.itemData(i) == current_mode:
                self.codec2_mode_combo.setCurrentIndex(i)
                break
        self.codec2_mode_combo.currentIndexChanged.connect(self._on_codec2_mode_changed)
        codec_layout.addWidget(self.codec2_mode_combo, 2, 1)

        info_label = QLabel(
            "Opus: High quality, moderate bandwidth (8-64 kbps). Best for most connections.\\n"
            "Codec2: Lower quality, very low bandwidth (0.7-3.2 kbps). For slow/mesh networks.\\n"
            "Note: Codec and bitrate are auto-negotiated with peer (lowest common setting)."
        )
        info_label.setStyleSheet("color: gray; font-size: 9pt;")
        info_label.setWordWrap(True)
        codec_layout.addWidget(info_label, 3, 0, 1, 2)

        codec_group.setLayout(codec_layout)
        parent_layout.addWidget(codec_group)

        self._update_codec_visibility()

    def _on_codec_changed(self, index: int) -> None:
        """Handle codec selection change."""
        codec_type = self.codec_combo.itemData(index)
        self.config.codec_type = codec_type
        self.config.save()
        self._update_codec_visibility()
        logger.info(f"Codec changed to: {codec_type}")

    def _on_opus_bitrate_changed(self, index: int) -> None:
        """Handle Opus bitrate change."""
        bitrate = self.opus_bitrate_combo.itemData(index)
        self.config.opus_bitrate = bitrate
        self.config.save()
        logger.info(f"Opus bitrate changed to: {bitrate}")

    def _on_codec2_mode_changed(self, index: int) -> None:
        """Handle Codec2 mode change."""
        mode = self.codec2_mode_combo.itemData(index)
        self.config.codec2_mode = mode
        self.config.save()
        logger.info(f"Codec2 mode changed to: {mode}")

    def _update_codec_visibility(self) -> None:
        """Update visibility of codec-specific settings."""
        codec_type = self.config.codec_type
        opus_visible = codec_type == "opus"
        codec2_visible = codec_type == "codec2"

        self.opus_bitrate_combo.setEnabled(opus_visible)
        self.codec2_mode_combo.setEnabled(codec2_visible)

    def _update_connection_status(self) -> None:
        """Update the RNS connection status indicator."""
        if self.reticulum_client and self.reticulum_client.reticulum:
            self.connection_label.setText("🟢 RNS: Connected")
            self.connection_label.setStyleSheet("color: green;")
        else:
            self.connection_label.setText("⚫ RNS: Connecting...")
            self.connection_label.setStyleSheet("color: gray;")

    def _get_codec_settings(
        self, call: Optional[CallInfo] = None
    ) -> tuple[str, int, int, int]:
        """Get codec settings, preferring negotiated over config defaults.

        Args:
            call: Current call info with potentially negotiated codec settings

        Returns:
            Tuple of (codec_type, opus_bitrate, opus_complexity, codec2_mode)
        """
        if call and call.negotiated_codec_type:
            codec_type = call.negotiated_codec_type
            if codec_type == "opus":
                opus_bitrate = call.negotiated_codec_bitrate or self.config.opus_bitrate
                codec2_mode = self.config.codec2_mode  # Not used but still passed
            else:  # codec2
                opus_bitrate = self.config.opus_bitrate  # Not used but still passed
                codec2_mode = call.negotiated_codec_bitrate or self.config.codec2_mode
        else:
            codec_type = self.config.codec_type
            opus_bitrate = self.config.opus_bitrate
            codec2_mode = self.config.codec2_mode

        return codec_type, opus_bitrate, self.config.opus_complexity, codec2_mode

    def _build_stats_panel(self, parent_layout: QVBoxLayout) -> None:
        """Create the audio quality statistics display panel."""
        stats_group = QGroupBox("Call Quality Metrics")
        stats_layout = QGridLayout()

        stats_layout.addWidget(QLabel("Quality:"), 0, 0)
        self.quality_label = QLabel("-")
        self.quality_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        stats_layout.addWidget(self.quality_label, 0, 1)

        stats_layout.addWidget(QLabel("RTT (ms):"), 0, 2)
        self.rtt_label = QLabel("-")
        stats_layout.addWidget(self.rtt_label, 0, 3)

        stats_layout.addWidget(QLabel("Packet Loss:"), 1, 0)
        self.loss_label = QLabel("-")
        stats_layout.addWidget(self.loss_label, 1, 1)

        stats_layout.addWidget(QLabel("Bitrate:"), 1, 2)
        stats_layout.addWidget(QLabel("Bitrate:"), 1, 2)
        self.bitrate_label = QLabel("-")
        stats_layout.addWidget(self.bitrate_label, 1, 3)

        stats_layout.addWidget(QLabel("Jitter (ms):"), 2, 0)
        self.jitter_label = QLabel("-")
        stats_layout.addWidget(self.jitter_label, 2, 1)

        stats_layout.addWidget(QLabel("Input:"), 3, 0)
        self.input_meter = QProgressBar()
        self.input_meter.setRange(0, 100)
        self.input_meter.setValue(0)
        self.input_meter.setTextVisible(False)
        self.input_meter.setStyleSheet(
            "QProgressBar::chunk { background-color: #4CAF50; }"
        )
        stats_layout.addWidget(self.input_meter, 3, 1, 1, 3)

        stats_layout.addWidget(QLabel("Output:"), 4, 0)
        self.output_meter = QProgressBar()
        self.output_meter.setRange(0, 100)
        self.output_meter.setValue(0)
        self.output_meter.setTextVisible(False)
        self.output_meter.setStyleSheet(
            "QProgressBar::chunk { background-color: #2196F3; }"
        )
        stats_layout.addWidget(self.output_meter, 4, 1, 1, 3)

        stats_group.setLayout(stats_layout)
        parent_layout.addWidget(stats_group)

    def _update_stats_display(self) -> None:
        """Update the stats panel with current metrics and security info."""
        metrics = media.get_current_metrics()
        security_info = media.get_security_info()

        if security_info:
            encrypted = security_info.get("encrypted", False)
            sas = security_info.get("sas_code")
            sas_verified = security_info.get("sas_verified", False)

            if not encrypted and hasattr(self, "_unencrypted_warning_shown"):
                if not self._unencrypted_warning_shown:
                    self._unencrypted_warning_shown = True
                    if not warn_unencrypted_connection(self):
                        # User chose to end the call
                        self.on_end_clicked()
                        return

            enc_icon = "[ENC]" if encrypted else "[!]"
            enc_text = "Encrypted" if encrypted else "UNENCRYPTED"

            if sas:
                verify_mark = "[V]" if sas_verified else ""
                sas_text = f" | SAS: {sas} {verify_mark}"
                self.verify_sas_btn.setEnabled(not sas_verified)
            else:
                sas_text = ""
                self.verify_sas_btn.setEnabled(False)

            self.security_label.setText(f"{enc_icon} {enc_text}{sas_text}")

            if encrypted and (sas_verified or not sas):
                text_color = "#4CAF50"  # green - secure
            elif encrypted:
                text_color = "#FF9800"  # orange - needs SAS verification
            else:
                text_color = "#F44336"  # red - unencrypted

            self.security_label.setStyleSheet(
                f"QLabel {{ color: {text_color}; border: 1px solid palette(mid); padding: 4px; font-family: monospace; font-weight: bold; }}"
            )
        else:
            self.security_label.setText("Security: [Not Connected]")
            self.security_label.setStyleSheet(
                "QLabel { border: 1px solid palette(mid); padding: 4px; font-family: monospace; }"
            )
            self.verify_sas_btn.setEnabled(False)
            self._unencrypted_warning_shown = False

        if not metrics:
            self.quality_label.setText("-")
            self.quality_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
            self.rtt_label.setText("-")
            self.loss_label.setText("-")
            self.bitrate_label.setText("-")
            self.jitter_label.setText("-")
            self.input_meter.setValue(0)
            self.output_meter.setValue(0)
            return

        quality = metrics.get_connection_quality()
        if quality == "Good":
            quality_color = "#4CAF50"  # green
        elif quality == "Fair":
            quality_color = "#FF9800"  # orange
        elif quality == "Poor":
            quality_color = "#F44336"  # red
        else:  # Unknown
            quality_color = "palette(text)"

        self.quality_label.setText(quality)
        self.quality_label.setStyleSheet(
            f"color: {quality_color}; font-weight: bold; font-size: 12pt;"
        )

        if metrics.rtt_avg is not None:
            rtt_text = f"{metrics.rtt_avg:.1f} ms"
            if metrics.rtt_min is not None and metrics.rtt_max is not None:
                rtt_text += f" ({metrics.rtt_min:.0f}-{metrics.rtt_max:.0f})"
            self.rtt_label.setText(rtt_text)
        else:
            self.rtt_label.setText("-")

        if metrics.packets_expected > 0:
            self.loss_label.setText(f"{metrics.loss_percentage:.1f}%")
        else:
            self.loss_label.setText("-")

        if metrics.avg_bitrate_kbps > 0:
            self.bitrate_label.setText(f"{metrics.avg_bitrate_kbps:.1f} kbps")
        else:
            self.bitrate_label.setText("-")

        self.jitter_label.setText(f"{metrics.jitter_ms:.0f} ms")

        self.input_meter.setValue(int(metrics.input_level * 100))
        self.output_meter.setValue(int(metrics.output_level * 100))

    def closeEvent(self, event) -> None:
        """Save configuration when window closes."""
        self.ringtone_player.cleanup()
        
        if self.peers_window:
            self.peers_window.close()

        self.config.window_geometry = (self.width(), self.height())

        if self.audio_input_device is not None:
            self.config.audio_input_device = self.audio_input_device
        if self.audio_output_device is not None:
            self.config.audio_output_device = self.audio_output_device

        remote_id = self.dest_input.text().strip()
        if remote_id:
            self.config.last_remote_id = remote_id

        if self.audio_input_device is not None:
            self.config.audio_input_device = self.audio_input_device
        if self.audio_output_device is not None:
            self.config.audio_output_device = self.audio_output_device

        self.config.save()
        event.accept()

    def append_event(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {text}"
        self._event_history.append(entry)
        self._event_history = self._event_history[-300:]
        self.log_view.setPlainText("\n".join(self._event_history))
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum()
        )

    def _format_remote_label(self, call: CallInfo | None) -> str:
        if not call:
            return "-"
        return call.display_name or call.remote_id

    def _update_remote_banner(self, call: CallInfo | None) -> None:
        self.remote_banner.setText(f"Remote: {self._format_remote_label(call)}")

    @Slot()
    def on_call_clicked(self) -> None:
        dest = self.dest_input.text().strip()
        if not dest:
            QMessageBox.warning(
                self, "Destination required", "Please enter a remote node ID."
            )
            return

        if dest == self.local_id:
            QMessageBox.information(
                self,
                "Talking to Yourself?",
                "Look, I get it. Sometimes you're the only one who really listens.\n\n"
                "But here's the thing: RNS (the networking layer) draws the line at you literally "
                "calling yourself. Apparently even distributed networks have boundaries.\n\n"
                "If you actually want to test the audio (wild idea, I know):\n"
                "• Fire up two separate LXST Phone instances with different identities\n"
                "• Find another human being to call (This is a phone after all.)\n\n"
                "Pro tip: The 'Simulate Incoming' button is great for testing the UI, "
                "but spoiler alert: there's no audio because, well, you'd be talking to yourself. "
                "We've been over this.",
            )
            return

        if self.peers_storage.is_blocked(dest):
            QMessageBox.warning(
                self,
                "Blocked Peer",
                f"This peer is blocked: {dest[:24]}...\n\n"
                "Unblock them in the Peers window to make calls.",
            )
            return

        if not self.peers_storage.is_verified(dest):
            if not warn_unverified_peer(dest, self):
                self.append_event("Call cancelled: peer not verified")
                return

        try:
            call = self.call_state.start_outgoing_call(self.local_id, dest)
            
            # Get the remote peer's display name from peers storage
            peer = self.peers_storage.get(dest)
            if peer:
                call.display_name = peer.display_name

            display_name = self.config.display_name or "LXST Phone User"
            msg = build_invite(
                from_id=self.local_id,
                to_id=dest,
                display_name=display_name,
                call_dest=self.reticulum_client.call_dest_hash,
                call_id=call.call_id,
                codec_type=self.config.codec_type,
                codec_bitrate=(
                    self.config.opus_bitrate
                    if self.config.codec_type == "opus"
                    else self.config.codec2_mode
                ),
            )
            self.reticulum_client.send_call_message(msg)
            self.call_state.mark_ringing()  # Transition to RINGING state for ringback tone
            self.append_event(
                f"Dialing {dest} (call_id={call.call_id[:8]}...). INVITE sent."
            )

        except Exception as exc:
            QMessageBox.warning(self, "Cannot start call", str(exc))
            self.call_state.end_call()
            self.append_event(f"Failed to start outgoing call: {exc}")

    @Slot()
    def on_end_clicked(self) -> None:
        call = self.call_state.current_call
        if not call:
            self.call_state.end_call()
            return
        try:
            msg = build_end(
                from_id=self.local_id,
                to_id=call.remote_id,
                call_id=call.call_id,
            )
            self.reticulum_client.send_call_message(msg)
            self.append_event(f"Sent CALL_END for {call.remote_id}")
        except Exception as exc:
            QMessageBox.warning(self, "Cannot end call", str(exc))
            self.append_event(f"Failed to send CALL_END: {exc}")
        finally:
            self.call_state.end_call()

    @Slot()
    def on_accept_clicked(self) -> None:
        call = self.call_state.current_call
        if not call:
            return
        try:
            codec_type, _, _, _ = self._get_codec_settings(call)
            if codec_type == "opus":
                codec_bitrate = (
                    call.negotiated_codec_bitrate or self.config.opus_bitrate
                )
            else:
                codec_bitrate = call.negotiated_codec_bitrate or self.config.codec2_mode

            if not self.media_active:
                codec_type_full, opus_bitrate, opus_complexity, codec2_mode = (
                    self._get_codec_settings(call)
                )
                media.start_media_session(
                    call,
                    self.reticulum_client,
                    audio_input_device=self.audio_input_device,
                    audio_output_device=self.audio_output_device,
                    audio_enabled=self.audio_enabled,
                    codec_type=codec_type_full,
                    opus_bitrate=opus_bitrate,
                    opus_complexity=self.config.opus_complexity,
                    codec2_mode=codec2_mode,
                )
                self.media_active = True
                logger.info("Started media session before sending CALL_ACCEPT (responder)")

            msg = build_accept(
                from_id=self.local_id,
                to_id=call.remote_id,
                call_id=call.call_id,
                call_dest=self.reticulum_client.call_dest_hash,
                codec_type=codec_type,
                codec_bitrate=codec_bitrate,
            )
            self.reticulum_client.send_call_message(msg)
            self.call_state.accept_current_call()
            self.append_event(
                f"Accepted call {call.call_id[:8]}... from {call.remote_id}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Cannot accept call", str(exc))
            self.append_event(f"Failed to send CALL_ACCEPT: {exc}")

    @Slot()
    def on_reject_clicked(self) -> None:
        call = self.call_state.current_call
        if not call:
            return

        self.call_history.add_call(
            direction="incoming",
            peer_id=call.remote_id,
            display_name=call.display_name or "Unknown",
            duration_sec=0,
            answered=False,
            call_id=call.call_id,
        )

        try:
            msg = build_reject(
                from_id=self.local_id,
                to_id=call.remote_id,
                call_id=call.call_id,
            )
            self.reticulum_client.send_call_message(msg)
            self.append_event(
                f"Rejected incoming call {call.call_id[:8]}... from {call.remote_id}"
            )
        except Exception as exc:
            QMessageBox.warning(self, "Cannot reject call", str(exc))
            self.append_event(f"Failed to send CALL_REJECT: {exc}")
        finally:
            self.call_state.reject_current_call()
            self.status_label.setText("Status: Call rejected")

    @Slot()
    def on_announce_clicked(self) -> None:
        """Send a manual presence announcement."""
        if self.reticulum_client:
            display_name = self.config.display_name or None
            self.reticulum_client.send_presence_announce(display_name=display_name)
            name_info = f" as '{display_name}'" if display_name else ""
            self.append_event(f"Sent presence announcement{name_info}")
        else:
            QMessageBox.warning(self, "Not ready", "Reticulum client not initialized")

    @Slot()
    def on_verify_sas_clicked(self) -> None:
        """Show SAS verification dialog."""
        security_info = media.get_security_info()
        if not security_info:
            return

        sas_code = security_info.get("sas_code")
        if not sas_code:
            QMessageBox.information(
                self,
                "No Security Code",
                "Security code not available yet. Wait for the connection to fully establish.",
            )
            return

        call = self.call_state.current_call
        remote_peer = call.remote_id if call else "Unknown"

        verified = show_sas_verification(sas_code, remote_peer, self)

        if verified:
            media.verify_sas()
            self.peers_storage.mark_verified(remote_peer)
            self.append_event(f"Security verified with {remote_peer[:16]}...")
            QMessageBox.information(
                self,
                "Security Verified",
                "Security codes match!\n\n"
                "This peer has been marked as verified.\n"
                "Future calls will be trusted.",
            )
        else:
            self.append_event("Security verification cancelled or failed")
            self.append_event("Cannot announce: Reticulum not initialized")

    @Slot()
    def on_reset_clicked(self) -> None:
        """
        Force-reset the UI/state to idle. Handy after unexpected failures.
        """
        if self.media_active:
            media.stop_media_session()
            self.media_active = False
        self.call_state.end_call()
        self.append_event("Reset to idle requested by user")

    @Slot()
    def on_simulate_incoming_clicked(self) -> None:
        """
        Developer helper: simulate an incoming invite so UI flows can be tested quickly.
        """
        self.simulate_incoming_invite()

    def simulate_incoming_invite(
        self, remote_id: str | None = None, display_name: str = "Simulated Caller"
    ) -> None:
        fake_remote = remote_id or f"sim-{self.local_id[-6:]}"
        call_id = new_call_id()
        call_dest = self.reticulum_client.call_dest_hash
        call_identity_key = self.reticulum_client.identity_key_b64()

        self.reticulum_client.known_peers[fake_remote] = (
            call_dest,
            call_identity_key,
        )

        msg = CallMessage(
            msg_type="CALL_INVITE",
            call_id=call_id,
            from_id=fake_remote,
            to_id=self.local_id,
            display_name=display_name,
            call_dest=call_dest,
            call_identity_key=call_identity_key,
            timestamp=time.time(),
        )
        self.append_event(f"Simulating incoming invite from {fake_remote}")
        self.handle_incoming_call_message(msg)

    def on_call_state_changed(self, phase: CallPhase, call: CallInfo | None) -> None:
        """
        Update the UI when the call state changes.
        """
        remote_label = self._format_remote_label(call)
        self._update_remote_banner(call)
        self.append_event(f"State -> {phase.name} (remote={remote_label})")

        if phase == CallPhase.IDLE:
            self.ringtone_player.stop()
            
            if self._call_start_time is not None and call:
                duration = int(time.time() - self._call_start_time)
                direction = "outgoing" if call.initiated_by_local else "incoming"
                self.call_history.add_call(
                    direction=direction,
                    peer_id=call.remote_id,
                    display_name=call.display_name or "Unknown",
                    duration_sec=duration,
                    answered=True,  # We only track if IN_CALL was reached
                    call_id=call.call_id,
                )
                self._call_start_time = None

            self.status_label.setText("Status: Idle")
            self.call_btn.setEnabled(True)
            self.end_btn.setEnabled(False)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(True)
            if self.media_active:
                media.stop_media_session()
                self.media_active = False
        elif phase == CallPhase.OUTGOING_CALL:
            self.status_label.setText(
                f"Status: Calling {remote_label or (call.remote_id if call else '')}"
            )
            self.call_btn.setEnabled(False)
            self.end_btn.setEnabled(True)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(False)
        elif phase == CallPhase.RINGING:
            self.ringtone_player.play_outgoing()
            
            self.status_label.setText(
                f"Status: Ringing {remote_label or (call.remote_id if call else '')}"
            )
            self.call_btn.setEnabled(False)
            self.end_btn.setEnabled(True)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(False)
        elif phase == CallPhase.INCOMING_CALL:
            self.ringtone_player.play_incoming()
            
            self.status_label.setText(f"Status: Incoming call from {remote_label}")
            self.call_btn.setEnabled(False)
            self.end_btn.setEnabled(False)
            self.accept_btn.setEnabled(True)
            self.reject_btn.setEnabled(True)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(False)
        elif phase == CallPhase.IN_CALL:
            self.ringtone_player.stop()
            
            if self._call_start_time is None:
                self._call_start_time = time.time()

            codec_info = ""
            if call and call.negotiated_codec_type:
                codec_type = call.negotiated_codec_type
                bitrate = call.negotiated_codec_bitrate
                if codec_type == "opus":
                    codec_info = f" [Opus @ {bitrate//1000} kbps]"
                elif codec_type == "codec2":
                    codec_info = f" [Codec2 @ {bitrate} bps]"

            self.status_label.setText(
                f"Status: In call with {remote_label}{codec_info}"
            )
            self.call_btn.setEnabled(False)
            self.end_btn.setEnabled(True)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(False)
            
            # Start media session if not already active (initiator case)
            if call and not self.media_active:
                codec_type, opus_bitrate, opus_complexity, codec2_mode = (
                    self._get_codec_settings(call)
                )

                media.start_media_session(
                    call,
                    self.reticulum_client,
                    audio_input_device=self.audio_input_device,
                    audio_output_device=self.audio_output_device,
                    audio_enabled=self.audio_enabled,
                    codec_type=codec_type,
                    opus_bitrate=opus_bitrate,
                    opus_complexity=self.config.opus_complexity,
                    codec2_mode=codec2_mode,
                )
                self.media_active = True
            
            # Always start the stats timer when entering IN_CALL state
            if not self.stats_timer.isActive():
                self.stats_timer.start()  # Start updating stats display
        elif phase == CallPhase.ENDED:
            self.ringtone_player.stop()
            
            self.status_label.setText("Status: Call ended")
            self.call_btn.setEnabled(True)
            self.end_btn.setEnabled(False)
            self.accept_btn.setEnabled(False)
            self.reject_btn.setEnabled(False)
            self.reset_btn.setEnabled(True)
            self.simulate_invite_btn.setEnabled(True)
            if self.media_active:
                media.stop_media_session()
                self.media_active = False
                self.stats_timer.stop()  # Stop updating stats display
                self._update_stats_display()  # Clear the display

    @Slot(object)
    def handle_incoming_call_message(self, msg: CallMessage) -> None:
        logger.debug(
            f"Incoming signaling message: {msg.msg_type} "
            f"from={msg.from_id} to={msg.to_id}, local_id={self.local_id}"
        )

        if msg.msg_type == "PRESENCE_ANNOUNCE":
            display_name = msg.display_name or "Unknown"
            self.append_event(
                f"Discovered peer: {msg.from_id[:16]}... ({display_name})"
            )
            self.peers_window.add_or_update_peer(msg.from_id, msg.display_name)
            peer_count = self.peers_window.get_peer_count()
            self.view_peers_btn.setText(f"Discovered Peers ({peer_count})")
            return

        self.append_event(
            f"RX {msg.msg_type} from {msg.from_id} (call_id={msg.call_id[:8]}...)"
        )

        current_call = self.call_state.current_call
        allowed, reason = self.msg_filter.evaluate(
            msg, current_call.call_id if current_call else None
        )
        if not allowed:
            if reason == "not_for_us":
                logger.debug("Message not for us, ignoring.")
                self.append_event("Ignored: message addressed to different node_id")
            elif reason == "duplicate":
                self.append_event(
                    f"Debounced duplicate {msg.msg_type} for {msg.call_id}"
                )
            elif reason == "unknown_call_idle":
                self.append_event(
                    f"Ignoring {msg.msg_type} with unknown call_id while idle"
                )
            elif reason == "foreign_call":
                active_id = current_call.call_id if current_call else "<none>"
                self.append_event(
                    f"Ignoring {msg.msg_type} for foreign call_id "
                    f"{msg.call_id[:8]}... (current={active_id[:8]}...)"
                )
            else:
                self.append_event(f"Ignored {msg.msg_type}: {reason}")
            return

        if msg.msg_type == "CALL_INVITE":
            remote_id = msg.from_id

            if self.peers_storage.is_blocked(remote_id):
                logger.info(
                    f"Auto-rejecting call from blocked peer: {remote_id[:16]}..."
                )
                self.append_event(f"Blocked peer {remote_id[:16]}... - auto-rejected")
                try:
                    reject = build_reject(
                        from_id=self.local_id,
                        to_id=remote_id,
                        call_id=msg.call_id,
                    )
                    self.reticulum_client.send_call_message(reject)
                except Exception as exc:
                    logger.error(f"Failed to send reject to blocked peer: {exc}")
                return

            if not self.rate_limiter.is_allowed(remote_id):
                stats = self.rate_limiter.get_peer_stats(remote_id)
                logger.warning(
                    f"Rate limit exceeded for {remote_id[:16]}...: "
                    f"{stats['calls_last_minute']}/min, {stats['calls_last_hour']}/hour"
                )
                self.append_event(
                    f"Rate limit exceeded from {remote_id[:16]}... - auto-rejected"
                )
                try:
                    reject = build_reject(
                        from_id=self.local_id,
                        to_id=remote_id,
                        call_id=msg.call_id,
                    )
                    self.reticulum_client.send_call_message(reject)
                except Exception as exc:
                    logger.error(f"Failed to send rate-limit reject: {exc}")
                return

            local_codec = self.config.codec_type
            local_bitrate = (
                self.config.opus_bitrate
                if local_codec == "opus"
                else self.config.codec2_mode
            )
            remote_codec = msg.codec_type or "opus"  # Default to opus if not specified
            remote_bitrate = msg.codec_bitrate or 24000  # Default bitrate

            negotiated_codec, negotiated_bitrate = negotiate_codec(
                local_codec, local_bitrate, remote_codec, remote_bitrate
            )

            # Get remote identity key from known_peers (from their announce)
            # instead of from the CALL_INVITE message (to keep packet size under MTU)
            remote_identity_key = None
            peer_info = self.reticulum_client.known_peers.get(remote_id)
            if peer_info:
                _, remote_identity_key = peer_info

            call = CallInfo(
                call_id=msg.call_id,
                local_id=self.local_id,
                remote_id=remote_id,
                display_name=msg.display_name,
                remote_call_dest=msg.call_dest,
                remote_identity_key=remote_identity_key,
                negotiated_codec_type=negotiated_codec,
                negotiated_codec_bitrate=negotiated_bitrate,
            )
            accepted = self.call_state.receive_incoming_invite(call)
            if not accepted:
                logger.info("Busy; rejecting invite automatically.")
                self.append_event("Busy; auto-rejecting incoming invite.")
                try:
                    reject = build_reject(
                        from_id=self.local_id,
                        to_id=remote_id,
                        call_id=msg.call_id,
                    )
                    self.reticulum_client.send_call_message(reject)
                except Exception as exc:
                    logger.error(f"Failed to send busy reject: {exc}")
                    self.append_event(f"Failed to send busy reject: {exc}")
                    QMessageBox.warning(self, "Reject failed", str(exc))
            else:
                self.append_event(
                    f"Incoming invite from {remote_id} (call_id={msg.call_id[:8]}...)"
                )
            return

        if msg.msg_type == "CALL_ACCEPT":
            if current_call:
                local_codec = self.config.codec_type
                local_bitrate = (
                    self.config.opus_bitrate
                    if local_codec == "opus"
                    else self.config.codec2_mode
                )
                remote_codec = msg.codec_type or "opus"
                remote_bitrate = msg.codec_bitrate or 24000

                negotiated_codec, negotiated_bitrate = negotiate_codec(
                    local_codec, local_bitrate, remote_codec, remote_bitrate
                )

                current_call.negotiated_codec_type = negotiated_codec
                current_call.negotiated_codec_bitrate = negotiated_bitrate

            # Get remote identity key from known_peers (from their announce)
            # instead of from the CALL_ACCEPT message (to keep packet size under MTU)
            remote_identity_key = None
            peer_info = self.reticulum_client.known_peers.get(msg.from_id)
            if peer_info:
                _, remote_identity_key = peer_info
            
            logger.debug(
                f"CALL_ACCEPT: call_dest={msg.call_dest}, "
                f"remote_identity_key={'present' if remote_identity_key else 'MISSING'}"
            )
            
            self.call_state.mark_remote_accepted(
                msg.call_id,
                remote_call_dest=msg.call_dest,
                remote_identity_key=remote_identity_key,
            )
            self.append_event("Remote accepted the call")
            return

        if msg.msg_type == "CALL_REJECT":
            self.call_state.mark_remote_rejected(msg.call_id)
            self.status_label.setText("Status: Call rejected by remote")
            self.append_event("Remote rejected the call")
            return

        if msg.msg_type == "CALL_END":
            self.call_state.remote_ended(msg.call_id)
            self.status_label.setText("Status: Call ended by remote")
            self.append_event("Remote ended the call")
            return

        logger.warning(f"Unsupported msg_type right now: {msg.msg_type}")
