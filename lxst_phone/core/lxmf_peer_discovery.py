"""
LXMF Peer Discovery for LXST Phone.

This module uses LXMF announces to discover peers with display names,
then makes them available for LXST telephony calls.

We don't implement LXMF messaging - just use it for peer discovery.
"""

import RNS
import LXMF
from PySide6.QtCore import QObject, Signal

from lxst_phone.logging_config import get_logger

logger = get_logger("lxmf_discovery")


class LXMFPeerDiscovery(QObject):
    """
    LXMF announce handler for discovering peers with display names.

    Emits signals when peers are discovered via LXMF announces.
    These peers can then be called via LXST telephony.
    """

    peer_discovered = Signal(str, str, str)

    def __init__(self, identity: RNS.Identity):
        """
        Initialize LXMF peer discovery.

        Args:
            identity: RNS Identity (same one used for LXST)
        """
        super().__init__()
        self.identity = identity
        self.aspect_filter = "lxmf.delivery"

        logger.info("Registering LXMF announce handler for peer discovery")
        RNS.Transport.register_announce_handler(self)

    def received_announce(
        self, destination_hash, announced_identity, app_data, announce_packet_hash
    ):
        """
        Called when an LXMF announce is received.

        Args:
            destination_hash: LXMF destination hash (bytes)
            announced_identity: RNS.Identity of the peer
            app_data: LXMF app_data containing display name
            announce_packet_hash: Hash of the announce packet
        """
        if not announced_identity:
            return

        identity_hash = announced_identity.hash.hex()

        display_name = LXMF.display_name_from_app_data(app_data)
        if not display_name:
            display_name = f"Peer {identity_hash[:8]}"

        lxst_dest_hash = RNS.Destination.hash_from_name_and_identity(
            "lxst.telephony", announced_identity  # Pass the full Identity object
        )
        lxst_dest_hash_hex = lxst_dest_hash.hex()

        try:
            RNS.Identity.remember(
                packet_hash=destination_hash,
                destination_hash=lxst_dest_hash,  # Store with LXST hash
                public_key=announced_identity.get_public_key(),
                app_data=app_data,
            )
            logger.debug(f"Remembered identity for {display_name}")
        except Exception as exc:
            logger.warning(f"Could not remember identity: {exc}")

        logger.debug(
            f"Discovered peer via LXMF: {display_name} ({identity_hash[:16]}...)"
        )
        self.peer_discovered.emit(identity_hash, display_name, lxst_dest_hash_hex)
