from __future__ import annotations

import json
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
    Reticulum wrapper for hybrid signaling:
    - PLAIN broadcast for discovery/presence announcements
    - SINGLE destinations for private call signaling (INVITE, ACCEPT, etc.)

    Discovery: Clients announce their signaling destination on PLAIN
    Signaling: Call messages are sent directly to recipient's SINGLE destination
    Media: Links use separate SINGLE media destination (existing)
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

        self.discovery_rx_dest: Optional[RNS.Destination] = None
        self.discovery_tx_dest: Optional[RNS.Destination] = None

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

        self.discovery_rx_dest = RNS.Destination(
            None,
            RNS.Destination.IN,
            RNS.Destination.PLAIN,
            self.app_name,
            "discovery",
        )
        self.discovery_rx_dest.set_packet_callback(self._discovery_packet_callback)
        logger.info(
            f"Created PLAIN discovery RX: {RNS.prettyhexrep(self.discovery_rx_dest.hash)}"
        )

        self.discovery_tx_dest = RNS.Destination(
            None,
            RNS.Destination.OUT,
            RNS.Destination.PLAIN,
            self.app_name,
            "discovery",
        )
        logger.info(
            f"Created PLAIN discovery TX: {RNS.prettyhexrep(self.discovery_tx_dest.hash)}"
        )

        logger.info(
            f"Hybrid signaling ready. "
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

    def _discovery_packet_callback(self, data: bytes, packet: RNS.Packet) -> None:
        """Handle PRESENCE_ANNOUNCE messages on PLAIN discovery channel."""
        logger.debug(f"Discovery packet: {len(data)} bytes")

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
        Send a call message using hybrid routing:
        - PRESENCE_ANNOUNCE: broadcast on PLAIN discovery channel
        - All other messages: send to recipient's SINGLE signaling destination
        """
        if not self.reticulum:
            raise RuntimeError("Reticulum not initialised")

        payload_bytes = json.dumps(msg.to_payload()).encode("utf-8")

        if msg.msg_type == "PRESENCE_ANNOUNCE":
            if not self.discovery_tx_dest:
                raise RuntimeError("Discovery TX destination not initialised")

            packet = RNS.Packet(self.discovery_tx_dest, payload_bytes)
            try:
                send_ok = packet.send()
            except Exception as exc:
                raise RuntimeError(f"Failed to queue discovery packet: {exc}") from exc

            if send_ok is False:
                raise RuntimeError("RNS.Packet.send() returned False")

            logger.info(f"Broadcast PRESENCE_ANNOUNCE ({len(payload_bytes)} bytes)")
            return

        if not msg.to_id:
            raise ValueError("to_id required for call signaling messages")

        peer_info = self.known_peers.get(msg.to_id)
        if not peer_info:
            raise RuntimeError(
                f"Unknown peer {msg.to_id[:16]}... - no signaling destination. "
                "Ensure peer has announced presence first."
            )

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
        """Broadcast presence announcement on PLAIN discovery channel."""
        from lxst_phone.core.signaling import build_announce

        announce_msg = build_announce(
            from_id=self.node_id,
            display_name=display_name,
            signaling_dest=self.signaling_dest_hash,
            signaling_identity_key=self.signaling_identity_key_b64(),
        )
        self.send_call_message(announce_msg)

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
