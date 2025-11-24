from __future__ import annotations

import json
import time
from typing import Callable, Optional
import base64
from pathlib import Path

import RNS

from lxst_phone.logging_config import get_logger
from lxst_phone.core.signaling import CallMessage
from lxst_phone.identity import load_or_create_identity

logger = get_logger("core.reticulum")


class ReticulumClient:
    """
    Reticulum wrapper for LXST Phone signaling and discovery.
    
    Discovery: Uses Reticulum's built-in announce mechanism
      - Each client announces its signaling destination with app_data
      - Announces propagate across all RNS interfaces (local, TCP, radio, etc.)
      - Announce handler filters for lxst_phone announces and stores peer info
    
    Signaling: SINGLE destinations for private call messages (INVITE, ACCEPT, etc.)
      - Each peer has a SINGLE signaling destination for receiving call control
      - Messages are sent as encrypted packets to recipient's signaling destination
    
    Media: Separate SINGLE destination for establishing voice Links
      - Uses RNS.Link for actual voice data transfer
      - Link established after call is accepted
    """

    def __init__(
        self,
        app_name: str = "lxst_phone",
        aspect: str = "signal",
        configpath: Optional[str] = None,
        identity_path: Optional[Path] = None,
        force_new_identity: bool = False,
    ) -> None:
        self.app_name = app_name
        self.aspect = aspect
        self.configpath = configpath
        self.identity_path = identity_path
        self.force_new_identity = force_new_identity

        self.reticulum: Optional[RNS.Reticulum] = None

        self.node_identity: Optional[RNS.Identity] = None
        self.node_id: str = "<uninitialised>"

        self.signaling_dest: Optional[RNS.Destination] = None

        self.media_dest: Optional[RNS.Destination] = None

        self.known_peers: dict[str, tuple[str, str]] = {}

        self.on_message: Optional[Callable[[CallMessage], None]] = None
        self.on_media_link: Optional[Callable[[RNS.Link], None]] = None

    def start(self) -> None:
        self.reticulum = RNS.Reticulum(self.configpath)

        if RNS.loglevel < RNS.LOG_INFO:
            RNS.loglevel = RNS.LOG_INFO

        self.node_identity = load_or_create_identity(
            identity_path=self.identity_path, force_new=self.force_new_identity
        )
        self.node_id = self.node_identity.hash.hex()
        self.signaling_dest = RNS.Destination(
            self.node_identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            self.app_name,
            "signaling",
        )
        self.signaling_dest.set_packet_callback(self._signaling_packet_callback)
        logger.info(
            f"Created SINGLE signaling destination: {RNS.prettyhexrep(self.signaling_dest.hash)}"
        )

        self.media_dest = RNS.Destination(
            self.node_identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            self.app_name,
            "media",
        )
        if hasattr(self.media_dest, "set_link_established_callback"):
            self.media_dest.set_link_established_callback(
                self._on_media_link_established
            )
        try:
            self.media_dest.announce()
            logger.info("Announced media destination")
        except Exception as exc:
            logger.error(f"Failed to announce media destination: {exc}")

        # Set up announce handler to discover other peers
        RNS.Transport.register_announce_handler(self._announce_handler)
        logger.info("Registered announce handler for peer discovery")

        logger.info(
            f"Signaling ready. "
            f"node_id={self.node_id}, "
            f"signaling={RNS.prettyhexrep(self.signaling_dest.hash)}, "
            f"media={RNS.prettyhexrep(self.media_dest.hash)}"
        )

    def stop(self) -> None:
        logger.info("Stopping ReticulumClient")

    @property
    def media_dest_hash(self) -> str:
        if not self.media_dest:
            raise RuntimeError("Media destination not initialised")
        return self.media_dest.hash.hex()

    @property
    def signaling_dest_hash(self) -> str:
        if not self.signaling_dest:
            raise RuntimeError("Signaling destination not initialised")
        return self.signaling_dest.hash.hex()

    def media_identity_key_b64(self) -> Optional[str]:
        """Export media identity public key (for media Links)."""
        return self._export_identity_public_key()

    def signaling_identity_key_b64(self) -> Optional[str]:
        """Export signaling identity public key (same as media, different dest)."""
        return self._export_identity_public_key()

    def _announce_handler(self, destination_hash: bytes, announced_identity: bytes, app_data: bytes) -> None:
        """
        Handle announces from other LXST Phone instances.
        This is called by RNS.Transport when any destination announces.
        """
        try:
            # Check if this is an lxst_phone signaling destination
            # We identify our announces by checking if app_data contains our protocol marker
            if app_data:
                try:
                    data = json.loads(app_data.decode('utf-8'))
                    if data.get('app') == 'lxst_phone' and data.get('type') == 'signaling':
                        node_id = announced_identity.hex()
                        signaling_dest_hash = destination_hash.hex()
                        identity_key_b64 = base64.b64encode(announced_identity).decode('ascii')
                        display_name = data.get('display_name', '')
                        
                        # Store peer info
                        self.known_peers[node_id] = (signaling_dest_hash, identity_key_b64)
                        
                        logger.info(
                            f"Discovered peer via announce: {node_id[:16]}... "
                            f"({display_name or 'unnamed'}) "
                            f"signaling={signaling_dest_hash[:16]}..."
                        )
                        
                        # Notify app layer if callback is set
                        if self.on_message:
                            # Create a PRESENCE_ANNOUNCE message for backwards compatibility
                            from lxst_phone.core.signaling import CallMessage
                            msg = CallMessage(
                                msg_type="PRESENCE_ANNOUNCE",
                                call_id="",
                                from_id=node_id,
                                to_id="",
                                display_name=display_name,
                                media_dest=signaling_dest_hash,
                                media_identity_key=identity_key_b64,
                                timestamp=time.time(),
                            )
                            self.on_message(msg)
                except (json.JSONDecodeError, UnicodeDecodeError, KeyError):
                    # Not our announce format, ignore
                    pass
        except Exception as exc:
            logger.error(f"Error handling announce: {exc}")

    def _old_discovery_packet_callback(self, data: bytes, packet: RNS.Packet) -> None:
        """
        DEPRECATED: Old PLAIN-based discovery (doesn't work across TCP interfaces).
        Kept for reference but no longer used.
        """
        logger.info(f"!!! Discovery packet received: {len(data)} bytes from {packet.packet_hash.hex() if hasattr(packet, 'packet_hash') else 'unknown'}")

        try:
            payload_text = data.decode("utf-8", errors="replace")
            payload = json.loads(payload_text)
            msg = CallMessage.from_payload(payload)

            if msg.msg_type == "PRESENCE_ANNOUNCE":
                if msg.media_dest and msg.media_identity_key:
                    self.known_peers[msg.from_id] = (
                        msg.media_dest,
                        msg.media_identity_key,
                    )
                    logger.info(
                        f"Discovered peer {msg.from_id[:16]}... "
                        f"signaling_dest={msg.media_dest[:16]}..."
                    )

                if self.on_message:
                    self.on_message(msg)
            else:
                logger.warning(
                    f"Unexpected message type on discovery channel: {msg.msg_type}"
                )
        except Exception as exc:
            logger.error(f"Failed to parse discovery packet: {exc}")

    def _signaling_packet_callback(self, data: bytes, packet: RNS.Packet) -> None:
        """Handle call signaling messages on SINGLE signaling channel."""
        logger.debug(f"Signaling packet: {len(data)} bytes")

        if not self.on_message:
            logger.warning("NO on_message handler registered, dropping packet")
            return

        try:
            payload_text = data.decode("utf-8", errors="replace")
            payload = json.loads(payload_text)
            msg = CallMessage.from_payload(payload)
            logger.debug(
                f"Parsed signaling: type={msg.msg_type}, "
                f"from={msg.from_id[:16]}..., to={msg.to_id[:16]}..."
            )
        except Exception as exc:
            logger.error(f"Failed to parse signaling message: {exc}")
            return

        try:
            self.on_message(msg)
        except Exception as exc:
            logger.error(f"Error in on_message handler: {exc}")

    def send_call_message(self, msg: CallMessage) -> None:
        """
        Send a call signaling message to a specific peer's SINGLE signaling destination.
        Note: PRESENCE_ANNOUNCE is no longer sent via this method - use send_presence_announce() instead.
        """
        if not self.reticulum:
            raise RuntimeError("Reticulum not initialised")

        if not msg.to_id:
            raise ValueError("to_id required for call signaling messages")

        peer_info = self.known_peers.get(msg.to_id)
        if not peer_info:
            raise RuntimeError(
                f"Unknown peer {msg.to_id[:16]}... - no signaling destination. "
                "Ensure peer has announced presence first."
            )

        payload_bytes = json.dumps(msg.to_payload()).encode("utf-8")

        signaling_dest_hash, signaling_identity_key = peer_info

        try:
            pub_key_bytes = base64.b64decode(signaling_identity_key)
            remote_identity = RNS.Identity(create_keys=False)
            remote_identity.load_public_key(pub_key_bytes)

            remote_signaling_dest = RNS.Destination(
                remote_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                self.app_name,
                "signaling",
            )

            if remote_signaling_dest.hash.hex() != signaling_dest_hash:
                logger.warning(
                    f"Reconstructed signaling dest {remote_signaling_dest.hash.hex()} "
                    f"!= expected {signaling_dest_hash}"
                )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to reconstruct remote signaling destination: {exc}"
            ) from exc

        packet = RNS.Packet(remote_signaling_dest, payload_bytes)
        try:
            send_ok = packet.send()
        except Exception as exc:
            raise RuntimeError(f"Failed to queue signaling packet: {exc}") from exc

        if send_ok is False:
            raise RuntimeError("RNS.Packet.send() returned False")

        logger.info(
            f"Sent {msg.msg_type} to {msg.to_id[:16]}... "
            f"via SINGLE dest {signaling_dest_hash[:16]}... ({len(payload_bytes)} bytes)"
        )

    def send_presence_announce(self, display_name: str | None = None) -> None:
        """
        Announce our signaling destination to the network.
        Uses Reticulum's built-in announce mechanism which propagates across all interfaces.
        """
        if not self.signaling_dest:
            logger.error("Cannot announce: signaling destination not initialized")
            return
        
        # Create app_data with our protocol marker and display name
        app_data = {
            'app': 'lxst_phone',
            'type': 'signaling',
            'display_name': display_name or '',
        }
        app_data_bytes = json.dumps(app_data).encode('utf-8')
        
        try:
            self.signaling_dest.announce(app_data=app_data_bytes)
            logger.info(
                f"Announced signaling destination "
                f"({display_name or 'no display name'}) "
                f"hash={RNS.prettyhexrep(self.signaling_dest.hash)}"
            )
        except Exception as exc:
            logger.error(f"Failed to announce signaling destination: {exc}")

    def _on_media_link_established(self, link: RNS.Link) -> None:
        logger.info(f"Inbound media link established: {link}")
        if self.on_media_link:
            try:
                self.on_media_link(link)
            except Exception as exc:
                logger.error(f"Error in on_media_link handler: {exc}")

    def _export_identity_public_key(self) -> Optional[str]:
        """Export the node identity's public key as base64."""
        if not self.node_identity:
            return None
        try:
            pub_key = self.node_identity.get_public_key()
            if pub_key:
                return base64.b64encode(pub_key).decode("ascii")
        except Exception as exc:
            logger.error(f"Failed to export identity public key: {exc}")
        return None

    def create_media_link(
        self,
        remote_media_dest: str,
        remote_identity_key_b64: Optional[str] = None,
        on_established: Optional[Callable[[RNS.Link], None]] = None,
        on_closed: Optional[Callable[[RNS.Link], None]] = None,
    ) -> RNS.Link:
        """
        Initiate an outbound RNS.Link to the remote media destination.

        Args:
            remote_media_dest: Hex-encoded destination hash (for verification)
            remote_identity_key_b64: Base64-encoded public key of remote identity
            on_established: Callback when link is established
            on_closed: Callback when link is closed
        """
        if not remote_identity_key_b64:
            raise ValueError("remote_identity_key_b64 is required")

        if not hasattr(RNS, "Link"):
            raise RuntimeError("RNS.Link not available")

        try:
            pub_key_bytes = base64.b64decode(remote_identity_key_b64)
            remote_identity = RNS.Identity(create_keys=False)
            remote_identity.load_public_key(pub_key_bytes)
            logger.debug(f"Reconstructed remote identity: {remote_identity.hash.hex()}")
        except Exception as exc:
            raise RuntimeError(f"Failed to reconstruct remote identity: {exc}") from exc

        try:
            remote_dest = RNS.Destination(
                remote_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                self.app_name,
                "media",
            )
            logger.debug(f"Created remote destination: {remote_dest.hash.hex()}")

            if remote_media_dest and remote_dest.hash.hex() != remote_media_dest:
                logger.warning(
                    f"Reconstructed dest hash {remote_dest.hash.hex()} "
                    f"!= expected {remote_media_dest}"
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to create remote destination: {exc}") from exc

        try:
            link = RNS.Link(remote_dest)
            logger.info(f"Created outbound media link to {remote_dest.hash.hex()}")
        except Exception as exc:
            raise RuntimeError(f"Failed to construct RNS.Link: {exc}") from exc

        if on_established:
            if hasattr(link, "set_link_established_callback"):
                link.set_link_established_callback(on_established)
            elif hasattr(link, "link_established_callback"):
                link.link_established_callback = on_established  # type: ignore[assignment]
        if on_closed:
            if hasattr(link, "set_link_closed_callback"):
                link.set_link_closed_callback(on_closed)
            elif hasattr(link, "link_closed_callback"):
                link.link_closed_callback = on_closed  # type: ignore[assignment]

        return link
