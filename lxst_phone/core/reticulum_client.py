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


class AnnounceHandler:
    """
    Handler for Reticulum announces from other LXST Phone instances.
    This class is registered with RNS.Transport to receive all announces.
    """
    
    def __init__(self, reticulum_client: 'ReticulumClient'):
        self.reticulum_client = reticulum_client
        self.aspect_filter = None  # Receive all announces and filter ourselves
    
    def received_announce(self, destination_hash: bytes, announced_identity: bytes, app_data: bytes) -> None:
        """
        Called by Reticulum when an announce is received.
        
        Args:
            destination_hash: Hash of the announced destination
            announced_identity: Public key of the announcing identity
            app_data: Application data included in the announce
        """
        try:
            # Parse identity first to determine if this is LXST Phone
            if isinstance(announced_identity, RNS.Identity):
                identity_obj = announced_identity
                node_id = identity_obj.hash.hex()
                identity_pub_key = identity_obj.get_public_key()
            else:
                try:
                    identity_obj = RNS.Identity(create_keys=False)
                    identity_obj.load_public_key(announced_identity)
                    node_id = identity_obj.hash.hex()
                    identity_pub_key = announced_identity
                except Exception as e:
                    logger.error(f"Could not load identity from public key: {e}")
                    node_id = destination_hash.hex()
                    identity_pub_key = announced_identity if isinstance(announced_identity, bytes) else None
            
            dest_hash_hex = destination_hash.hex()

            display_name = ""
            is_lxst_phone = False
            if app_data:
                try:
                    data = json.loads(app_data.decode('utf-8'))
                    logger.debug(f"Parsed app_data: {data}")

                    if data.get('app') == 'lxst_phone':
                        is_lxst_phone = True
                        display_name = data.get('display_name', '')
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Non-LXST Phone announce, silently ignore
                    pass

            if not is_lxst_phone:
                # Silently ignore non-LXST Phone announces
                return

            # Log only LXST Phone announces
            logger.debug(
                f"LXST Phone announce! dest_hash={dest_hash_hex[:16]}... "
                f"from identity {node_id[:16]}... display_name='{display_name}'"
            )

            if node_id == self.reticulum_client.node_id:
                logger.debug(f"Ignoring our own announce")
                return

            if identity_pub_key:
                identity_key_b64 = base64.b64encode(identity_pub_key).decode('ascii')
            else:
                logger.warning(f"No public key available for peer {node_id[:16]}...")
                return
            
            self.reticulum_client.known_peers[node_id] = (dest_hash_hex, identity_key_b64)
            
            logger.info(
                f"Discovered peer via announce: {node_id[:16]}... "
                f"({display_name or 'unnamed'}) "
                f"call_dest={dest_hash_hex[:16]}..."
            )

            if self.reticulum_client.on_message:
                from lxst_phone.core.signaling import CallMessage
                msg = CallMessage(
                    msg_type="PRESENCE_ANNOUNCE",
                    call_id="",
                    from_id=node_id,
                    to_id="",
                    display_name=display_name,
                    call_dest=dest_hash_hex,
                    call_identity_key=identity_key_b64,
                    timestamp=time.time(),
                )
                self.reticulum_client.on_message(msg)
                
        except Exception as exc:
            logger.error(f"Error in announce handler: {exc}", exc_info=True)


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

        self.call_dest: Optional[RNS.Destination] = None

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
        self.call_dest = RNS.Destination(
            self.node_identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            self.app_name,
            "call",
        )
        self.call_dest.set_packet_callback(self._signaling_packet_callback)
        if hasattr(self.call_dest, "set_link_established_callback"):
            self.call_dest.set_link_established_callback(
                self._on_media_link_established
            )
        logger.info(
            f"Created SINGLE call destination: {RNS.prettyhexrep(self.call_dest.hash)}"
        )

        self.announce_handler = AnnounceHandler(self)
        RNS.Transport.register_announce_handler(self.announce_handler)
        logger.info("Registered announce handler for peer discovery")

        logger.info(
            f"Call destination ready. "
            f"node_id={self.node_id}, "
            f"call_dest={RNS.prettyhexrep(self.call_dest.hash)}"
        )

    def stop(self) -> None:
        logger.info("Stopping ReticulumClient")

    @property
    def call_dest_hash(self) -> str:
        if not self.call_dest:
            raise RuntimeError("Call destination not initialised")
        return self.call_dest.hash.hex()

    def identity_key_b64(self) -> Optional[str]:
        """Export identity public key."""
        return self._export_identity_public_key()

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
                if msg.call_dest and msg.call_identity_key:
                    self.known_peers[msg.from_id] = (
                        msg.call_dest,
                        msg.call_identity_key,
                    )
                    logger.info(
                        f"Discovered peer {msg.from_id[:16]}... "
                        f"call_dest={msg.call_dest[:16]}..."
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
        Send a call signaling message to a specific peer's SINGLE call destination.
        Note: PRESENCE_ANNOUNCE is no longer sent via this method - use send_presence_announce() instead.
        """
        if not self.reticulum:
            raise RuntimeError("Reticulum not initialised")

        if not msg.to_id:
            raise ValueError("to_id required for call signaling messages")

        peer_info = self.known_peers.get(msg.to_id)
        if not peer_info:
            raise RuntimeError(
                f"Unknown peer {msg.to_id[:16]}... - no call destination. "
                "Ensure peer has announced presence first."
            )

        payload_bytes = json.dumps(msg.to_payload()).encode("utf-8")

        call_dest_hash, call_identity_key = peer_info

        try:
            pub_key_bytes = base64.b64decode(call_identity_key)
            remote_identity = RNS.Identity(create_keys=False)
            remote_identity.load_public_key(pub_key_bytes)

            remote_call_dest = RNS.Destination(
                remote_identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                self.app_name,
                "call",
            )

            if remote_call_dest.hash.hex() != call_dest_hash:
                logger.warning(
                    f"Reconstructed call dest {remote_call_dest.hash.hex()} "
                    f"!= expected {call_dest_hash}"
                )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to reconstruct remote call destination: {exc}"
            ) from exc

        packet = RNS.Packet(remote_call_dest, payload_bytes)
        try:
            send_ok = packet.send()
        except Exception as exc:
            raise RuntimeError(f"Failed to queue signaling packet: {exc}") from exc

        if send_ok is False:
            raise RuntimeError("RNS.Packet.send() returned False")

        logger.info(
            f"Sent {msg.msg_type} to {msg.to_id[:16]}... "
            f"via SINGLE dest {call_dest_hash[:16]}... ({len(payload_bytes)} bytes)"
        )

    def send_presence_announce(self, display_name: str | None = None) -> None:
        """
        Announce our call destination to the network.
        Uses Reticulum's built-in announce mechanism which propagates across all interfaces.
        """
        if not self.call_dest:
            logger.error("Cannot announce: call destination not initialized")
            return

        app_data = {
            'app': 'lxst_phone',
            'display_name': display_name or '',
        }
        app_data_bytes = json.dumps(app_data).encode('utf-8')
        
        try:
            self.call_dest.announce(app_data=app_data_bytes)
            logger.info(
                f"Announced call destination "
                f"({display_name or 'no display name'}) "
                f"hash={RNS.prettyhexrep(self.call_dest.hash)}"
            )
        except Exception as exc:
            logger.error(f"Failed to announce call destination: {exc}")

    def _on_media_link_established(self, link: RNS.Link) -> None:
        logger.info(f"Inbound media link established: {link.hash.hex() if hasattr(link, 'hash') else link}")
        logger.debug(f"Link details: status={getattr(link, 'status', '?')}, encrypted={getattr(link, 'encryption_enabled', getattr(link, 'encrypted', '?'))}")
        
        if self.on_media_link:
            try:
                self.on_media_link(link)
            except Exception as exc:
                logger.error(f"Error in on_media_link handler: {exc}")
        else:
            logger.warning("Inbound media link received but no on_media_link handler registered! Closing link.")
            try:
                if hasattr(link, "teardown"):
                    link.teardown()
            except Exception as exc:
                logger.error(f"Error tearing down unhandled link: {exc}")

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
        remote_call_dest: str,
        remote_identity_key_b64: Optional[str] = None,
        on_established: Optional[Callable[[RNS.Link], None]] = None,
        on_closed: Optional[Callable[[RNS.Link], None]] = None,
    ) -> RNS.Link:
        """
        Initiate an outbound RNS.Link to the remote call destination.

        Args:
            remote_call_dest: Hex-encoded destination hash (for verification)
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
                "call",
            )
            logger.debug(f"Created remote destination: {remote_dest.hash.hex()}")

            if remote_call_dest and remote_dest.hash.hex() != remote_call_dest:
                logger.warning(
                    f"Reconstructed dest hash {remote_dest.hash.hex()} "
                    f"!= expected {remote_call_dest}"
                )
        except Exception as exc:
            raise RuntimeError(f"Failed to create remote destination: {exc}") from exc

        try:
            link = RNS.Link(remote_dest)
            logger.info(f"Created outbound media link to {remote_dest.hash.hex()}")
            logger.debug(f"Link object: status={getattr(link, 'status', 'no status attr')}, callbacks set: established={on_established is not None}, closed={on_closed is not None}")
        except Exception as exc:
            raise RuntimeError(f"Failed to construct RNS.Link: {exc}") from exc

        if on_established:
            if hasattr(link, "set_link_established_callback"):
                link.set_link_established_callback(on_established)
                logger.debug("Set link established callback via set_link_established_callback")
            elif hasattr(link, "link_established_callback"):
                link.link_established_callback = on_established  # type: ignore[assignment]
                logger.debug("Set link established callback via link_established_callback property")
        if on_closed:
            if hasattr(link, "set_link_closed_callback"):
                link.set_link_closed_callback(on_closed)
                logger.debug("Set link closed callback via set_link_closed_callback")
            elif hasattr(link, "link_closed_callback"):
                link.link_closed_callback = on_closed  # type: ignore[assignment]
                logger.debug("Set link closed callback via link_closed_callback property")

        return link
