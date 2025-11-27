"""
LXMF Announcer - Announce LXMF destination so others can discover this phone.

This allows Sideband, MeshChat, and other LXMF clients to discover LXST Phone
with a display name. We only announce the LXMF destination for peer discovery;
we don't implement LXMF messaging (LXST Phone is telephony-only).
"""

import RNS
import LXMF
from lxst_phone.logging_config import get_logger

logger = get_logger("lxmf_announcer")


class LXMFAnnouncer:
    """
    Announces LXMF destination for peer discovery.

    This creates an LXMF destination and announces it with app_data containing
    the display name, allowing Sideband/MeshChat users to discover this phone.
    The LXMF destination is only for discovery - we don't handle LXMF messages.
    """

    def __init__(self, identity: RNS.Identity, display_name: str = ""):
        """
        Initialize LXMF announcer.

        Args:
            identity: RNS identity to use for LXMF destination
            display_name: Display name to announce (empty = use node ID)
        """
        self.identity = identity
        self._display_name = display_name or f"LXST Phone {identity.hash.hex()[:8]}"

        self.lxmf_destination = RNS.Destination(
            identity, RNS.Destination.IN, RNS.Destination.SINGLE, "lxmf", "delivery"
        )

        self.lxmf_destination.set_packet_callback(self._packet_callback)

        logger.info(f"LXMF destination created: {self.lxmf_destination.hash.hex()}")
        logger.info(f"Display name: {self._display_name}")

    def _packet_callback(self, data, packet):
        """
        Handle incoming packets to LXMF destination.

        We don't implement LXMF messaging, so just log and ignore.
        """
        logger.debug(f"Received packet on LXMF destination (ignored - telephony only)")

    @property
    def display_name(self) -> str:
        """Get current display name."""
        return self._display_name

    @display_name.setter
    def display_name(self, value: str) -> None:
        """
        Set display name and re-announce if changed.

        Args:
            value: New display name
        """
        if value and value != self._display_name:
            old_name = self._display_name
            self._display_name = value
            logger.info(f"Display name changed: '{old_name}' -> '{value}'")
            self.announce()

    def announce(self, path_response: bool = False) -> None:
        """
        Announce LXMF destination with display name.

        Args:
            path_response: Whether this is a path response announcement
        """
        app_data = self._display_name.encode("utf-8")

        self.lxmf_destination.announce(app_data=app_data, path_response=path_response)

        logger.info(f"Announced LXMF destination with name: {self._display_name}")
