"""
Security-related dialogs for LXST Phone.

Includes SAS verification, security warnings, and encryption status displays.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
)


class SASVerificationDialog(QDialog):
    """
    Dialog for verifying Short Authentication String (SAS) codes.

    Displays the SAS code prominently and explains the verification process.
    """

    def __init__(self, sas_code: str, remote_peer: str, parent=None):
        super().__init__(parent)
        self.sas_code = sas_code
        self.remote_peer = remote_peer
        self.verified = False

        self.setWindowTitle("Verify Security Code")
        self.setModal(True)
        self.setMinimumWidth(450)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Create the dialog UI."""
        layout = QVBoxLayout()

        title = QLabel("Verify Security Code")
        title.setStyleSheet("font-size: 16pt; font-weight: bold; color: #2196F3;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        peer_label = QLabel(f"Calling: {self.remote_peer[:24]}...")
        peer_label.setStyleSheet("font-size: 11pt; color: #666;")
        peer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(peer_label)

        layout.addSpacing(20)

        sas_display = QLabel(self.sas_code)
        sas_display.setStyleSheet(
            "font-size: 32pt; font-weight: bold; font-family: monospace; "
            "color: #2196F3; background-color: #E3F2FD; padding: 20px; "
            "border: 2px solid #2196F3; border-radius: 8px;"
        )
        sas_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sas_display)

        layout.addSpacing(20)

        instructions = QLabel(
            "To verify this call is secure:\n\n"
            "1. Ask the other person to read their security code\n"
            "2. Compare it with the code shown above\n"
            "3. If they match exactly, click 'Codes Match'\n"
            "4. If they don't match, click 'Codes Don't Match'\n\n"
            "If the codes don't match, someone may be intercepting your call!"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("font-size: 10pt; line-height: 1.4;")
        layout.addWidget(instructions)

        layout.addSpacing(20)

        button_layout = QHBoxLayout()

        match_btn = QPushButton("Codes Match")
        match_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "font-size: 12pt; font-weight: bold; padding: 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #45a049; }"
        )
        match_btn.clicked.connect(self._on_codes_match)
        button_layout.addWidget(match_btn)

        no_match_btn = QPushButton("Codes Don't Match")
        no_match_btn.setStyleSheet(
            "QPushButton { background-color: #F44336; color: white; "
            "font-size: 12pt; font-weight: bold; padding: 12px; border-radius: 4px; } "
            "QPushButton:hover { background-color: #da190b; }"
        )
        no_match_btn.clicked.connect(self._on_codes_dont_match)
        button_layout.addWidget(no_match_btn)

        layout.addLayout(button_layout)

        later_btn = QPushButton("Verify Later")
        later_btn.setStyleSheet("padding: 8px;")
        later_btn.clicked.connect(self.reject)
        layout.addWidget(later_btn)

        self.setLayout(layout)

    def _on_codes_match(self) -> None:
        """Handle codes matching."""
        self.verified = True
        self.accept()

    def _on_codes_dont_match(self) -> None:
        """Handle codes not matching - serious security warning."""
        reply = QMessageBox.warning(
            self,
            "Security Alert",
            "The security codes don't match!\n\n"
            "This could mean:\n"
            "• Someone is intercepting your call (man-in-the-middle attack)\n"
            "• There's a network issue\n"
            "• One of you is using an outdated version\n\n"
            "Do you want to end this call for security reasons?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.verified = False
            self.reject()


class UnverifiedPeerWarning(QMessageBox):
    """Warning dialog when calling an unverified peer."""

    def __init__(self, peer_id: str, parent=None):
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Warning)
        self.setWindowTitle("Unverified Peer")
        self.setText("Calling Unverified Peer")
        self.setInformativeText(
            f"You are about to call:\n{peer_id}\n\n"
            "This peer has not been verified. You should:\n"
            "• Verify the security code during the call\n"
            "• Confirm the identity through another channel\n\n"
            "Continue with call?"
        )
        self.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        self.setDefaultButton(QMessageBox.StandardButton.No)


class UnencryptedConnectionWarning(QMessageBox):
    """Critical warning when connection is not encrypted."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(QMessageBox.Icon.Critical)
        self.setWindowTitle("Security Alert")
        self.setText("UNENCRYPTED CONNECTION")
        self.setInformativeText(
            "This call is NOT encrypted!\n\n"
            "Your conversation can be intercepted by:\n"
            "• Network administrators\n"
            "• Anyone on the same network\n"
            "• Malicious third parties\n\n"
            "This should not happen with Reticulum. "
            "There may be a serious configuration issue.\n\n"
            "Do you want to continue?"
        )
        self.setStandardButtons(
            QMessageBox.StandardButton.No | QMessageBox.StandardButton.Yes
        )
        self.setDefaultButton(QMessageBox.StandardButton.No)
        self.setStyleSheet("QLabel { color: #d32f2f; }")


def show_sas_verification(sas_code: str, remote_peer: str, parent=None) -> bool:
    """
    Show SAS verification dialog and return whether codes were verified.

    Args:
        sas_code: The SAS code to display
        remote_peer: The remote peer's node ID
        parent: Parent widget

    Returns:
        True if user verified codes match, False otherwise
    """
    dialog = SASVerificationDialog(sas_code, remote_peer, parent)
    dialog.exec()
    return dialog.verified


def warn_unverified_peer(peer_id: str, parent=None) -> bool:
    """
    Warn about calling an unverified peer.

    Args:
        peer_id: The peer's node ID
        parent: Parent widget

    Returns:
        True if user wants to continue, False to cancel call
    """
    dialog = UnverifiedPeerWarning(peer_id, parent)
    result = dialog.exec()
    return result == QMessageBox.StandardButton.Yes


def warn_unencrypted_connection(parent=None) -> bool:
    """
    Show critical warning about unencrypted connection.

    Args:
        parent: Parent widget

    Returns:
        True if user wants to continue anyway (not recommended), False to end call
    """
    dialog = UnencryptedConnectionWarning(parent)
    result = dialog.exec()
    return result == QMessageBox.StandardButton.Yes
