"""
Peers/Phonebook window for LXST Phone.

Shows discovered peers from presence announcements and allows selecting them
to auto-fill the remote ID field for calls.
"""

from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
)
from datetime import datetime
from lxst_phone.peers_storage import PeersStorage, PeerRecord


def format_last_seen(last_seen: datetime) -> str:
    """Format last seen time as relative string."""
    delta = datetime.now() - last_seen
    if delta.seconds < 60:
        return "just now"
    elif delta.seconds < 3600:
        mins = delta.seconds // 60
        return f"{mins}m ago"
    elif delta.seconds < 86400:
        hours = delta.seconds // 3600
        return f"{hours}h ago"
    else:
        days = delta.days
        return f"{days}d ago"


class PeersWindow(QWidget):
    """Window showing discovered peers and allowing selection."""

    peerSelected = Signal(str)  # node_id

    def __init__(self, peers_storage: PeersStorage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Discovered Peers")
        self.resize(500, 400)

        self.peers_storage = peers_storage

        self._build_ui()

    def _build_ui(self):
        """Build the peers window UI."""
        layout = QVBoxLayout()

        title = QLabel("Discovered Peers")
        title.setStyleSheet("font-weight: bold; font-size: 14pt;")
        layout.addWidget(title)

        info = QLabel("Peers discovered through presence announcements:")
        info.setStyleSheet("color: gray;")
        layout.addWidget(info)

        self.peer_list = QListWidget()
        self.peer_list.setSelectionMode(QListWidget.SingleSelection)
        self.peer_list.itemDoubleClicked.connect(self._on_peer_double_clicked)
        layout.addWidget(self.peer_list)

        btn_layout = QHBoxLayout()

        self.select_btn = QPushButton("Select Peer")
        self.select_btn.setEnabled(False)
        self.select_btn.clicked.connect(self._on_select_clicked)
        btn_layout.addWidget(self.select_btn)

        self.block_btn = QPushButton("Block")
        self.block_btn.setToolTip("Block this peer (auto-reject calls)")
        self.block_btn.setEnabled(False)
        self.block_btn.clicked.connect(self._on_block_clicked)
        btn_layout.addWidget(self.block_btn)

        self.unblock_btn = QPushButton("Unblock")
        self.unblock_btn.setToolTip("Unblock this peer")
        self.unblock_btn.setEnabled(False)
        self.unblock_btn.clicked.connect(self._on_unblock_clicked)
        btn_layout.addWidget(self.unblock_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_list)
        btn_layout.addWidget(self.refresh_btn)

        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self._on_clear_clicked)
        btn_layout.addWidget(self.clear_btn)

        btn_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.close)
        btn_layout.addWidget(self.close_btn)

        layout.addLayout(btn_layout)

        self.peer_list.itemSelectionChanged.connect(self._on_selection_changed)

        self.setLayout(layout)

        self._refresh_list()

    def _on_selection_changed(self):
        """Enable/disable buttons based on selection."""
        selected_items = self.peer_list.selectedItems()
        has_selection = len(selected_items) > 0
        self.select_btn.setEnabled(has_selection)

        if has_selection:
            item = selected_items[0]
            node_id = item.data(Qt.UserRole)
            peer = self.peers_storage.get(node_id)
            if peer:
                self.block_btn.setEnabled(not peer.blocked)
                self.unblock_btn.setEnabled(peer.blocked)
            else:
                self.block_btn.setEnabled(False)
                self.unblock_btn.setEnabled(False)
        else:
            self.block_btn.setEnabled(False)
            self.unblock_btn.setEnabled(False)

    def _on_select_clicked(self):
        """Handle select button click."""
        selected_items = self.peer_list.selectedItems()
        if selected_items:
            item = selected_items[0]
            node_id = item.data(Qt.UserRole)
            self.peerSelected.emit(node_id)
            self.close()

    def _on_peer_double_clicked(self, item: QListWidgetItem):
        """Handle double-click on peer."""
        node_id = item.data(Qt.UserRole)
        self.peerSelected.emit(node_id)
        self.close()

    def _on_block_clicked(self):
        """Block the selected peer."""
        selected_items = self.peer_list.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        node_id = item.data(Qt.UserRole)
        peer = self.peers_storage.get(node_id)

        if peer:
            self.peers_storage.mark_blocked(node_id)
            self._refresh_list()

    def _on_unblock_clicked(self):
        """Unblock the selected peer."""
        selected_items = self.peer_list.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        node_id = item.data(Qt.UserRole)
        peer = self.peers_storage.get(node_id)

        if peer:
            self.peers_storage.unblock(node_id)
            self._refresh_list()

    def _on_clear_clicked(self):
        """Clear all discovered peers."""
        self.peers_storage.clear()
        self.peers_storage.save()
        self._refresh_list()

    def _refresh_list(self):
        """Refresh the peer list display."""
        self.peer_list.clear()

        all_peers = self.peers_storage.get_all()
        sorted_peers = sorted(all_peers, key=lambda x: x.last_seen, reverse=True)

        for peer_info in sorted_peers:
            node_id = peer_info.node_id
            short_id = node_id[:16] + "..." if len(node_id) > 16 else node_id

            status_icons = []
            if peer_info.verified:
                status_icons.append("[Verified]")
            if peer_info.blocked:
                status_icons.append("[Blocked]")

            status = f" [{' '.join(status_icons)}]" if status_icons else ""
            label = f"{peer_info.display_name} ({short_id}) - {format_last_seen(peer_info.last_seen)}{status}"

            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, node_id)  # Store full node_id

            if peer_info.blocked:
                item.setForeground(Qt.gray)

            tooltip = (
                f"Display Name: {peer_info.display_name}\n"
                f"Node ID: {node_id}\n"
                f"Last Seen: {peer_info.last_seen.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Announcements: {peer_info.announce_count}"
            )
            item.setToolTip(tooltip)

            self.peer_list.addItem(item)

    def add_or_update_peer(self, node_id: str, display_name: str | None = None):
        """
        Add a new peer or update existing peer information.

        Args:
            node_id: The peer's node ID
            display_name: The peer's display name (optional)
        """
        self.peers_storage.add_or_update(node_id, display_name)
        self.peers_storage.save()
        self._refresh_list()

    def get_peer_count(self) -> int:
        """Get the number of discovered peers."""
        return len(self.peers_storage.peers)
