"""
LXST Telephone wrapper for lxst_phone.

This is a thin wrapper around LXST.Primitives.Telephone that:
1. Manages the Telephone instance lifecycle
2. Provides Qt-friendly callbacks (emit signals)
3. Handles configuration from our Config
"""

import hashlib
import RNS
import LXST
from LXST.Primitives.Telephony import Telephone, Signalling, Profiles
from LXST.Filters import BandPass, AGC
from PySide6.QtCore import QObject, Signal

from lxst_phone.config import Config
from lxst_phone.logging_config import get_logger

logger = get_logger("telephone")


class TelephoneManager(QObject):
    """
    Qt-friendly wrapper around LXST Telephone.

    Emits Qt signals for UI updates:
    - call_ringing(identity_hash)
    - call_established(identity_hash)
    - call_ended(identity_hash)
    - call_busy(identity_hash)
    - call_rejected(identity_hash)
    """

    call_ringing = Signal(object, str)  # identity (RNS.Identity), identity_hash (hex)
    call_established = Signal(str)  # identity_hash (hex)
    call_ended = Signal(str)  # identity_hash (hex)
    call_busy = Signal(str)  # identity_hash (hex)
    call_rejected = Signal(str)  # identity_hash (hex)
    peer_announced = Signal(str, str)  # identity_hash (hex), destination_hash (hex)

    def __init__(self, identity: RNS.Identity, config: Config):
        """
        Initialize TelephoneManager.

        Args:
            identity: RNS Identity for this telephone
            config: Application configuration
        """
        super().__init__()
        self.config = config
        self.identity = identity

        default_profile = config.get(
            "codec", "default_profile", Profiles.QUALITY_MEDIUM
        )

        logger.info("Creating LXST Telephone instance")
        self.telephone = Telephone(
            identity=identity,
            ring_time=30,  # Ring timeout in seconds
            wait_time=60,  # Call establishment timeout
        )

        if config.use_audio_filters and config.filter_type != "none":
            logger.info(f"Configuring audio filters (type: {config.filter_type})")

            if config.use_agc:
                agc_target = config.get("audio", "agc_target_level", -12.0)
                agc_max_gain = config.get("audio", "agc_max_gain", 12.0)
                logger.info(
                    f"Enabling AGC (target: {agc_target} dBFS, max gain: {agc_max_gain} dB)"
                )
                self.telephone.enable_agc(True)
            else:
                logger.info("AGC disabled")
                self.telephone.disable_agc()

            logger.info("Audio filters will be applied during call setup")
        else:
            logger.info("Audio filters disabled")
            self.telephone.disable_agc()

        self.telephone.set_ringing_callback(self._on_ringing)
        self.telephone.set_established_callback(self._on_established)
        self.telephone.set_ended_callback(self._on_ended)
        self.telephone.set_busy_callback(self._on_busy)
        self.telephone.set_rejected_callback(self._on_rejected)

        if config.audio_input_device is not None:
            logger.debug(f"Setting microphone to device {config.audio_input_device}")
            self.telephone.set_microphone(config.audio_input_device)

        if config.audio_output_device is not None:
            logger.debug(f"Setting speaker to device {config.audio_output_device}")
            self.telephone.set_speaker(config.audio_output_device)

        if config.announce_on_start:
            logger.info("Announcing telephone service on startup")
            self.telephone.announce()

        self.aspect_filter = "lxst.telephony"
        logger.info(f"Registering announce handler for {self.aspect_filter}")
        RNS.Transport.register_announce_handler(self)

        logger.info("TelephoneManager initialized successfully")

    def call(self, identity: RNS.Identity, profile: int = None):
        """
        Initiate outgoing call.

        Args:
            identity: RNS Identity to call
            profile: LXST Profile to use (from Profiles class). If None, uses config default.
        """
        if profile is None:
            profile = self.config.get(
                "codec", "default_profile", Profiles.QUALITY_MEDIUM
            )

        identity_hash = identity.hash.hex()
        logger.info(
            f"Initiating call to {identity_hash[:16]}... with profile {profile:02x}"
        )

        try:
            self.telephone.call(identity, profile=profile)
        except Exception as exc:
            logger.error(f"Failed to initiate call: {exc}")
            raise

    def answer(self, identity: RNS.Identity):
        """
        Answer incoming call.

        Args:
            identity: RNS Identity of caller
        """
        identity_hash = identity.hash.hex()
        logger.info(f"Answering call from {identity_hash[:16]}...")

        try:
            self.telephone.answer(identity)
        except Exception as exc:
            logger.error(f"Failed to answer call: {exc}")
            raise

    def hangup(self):
        """Hang up current call."""
        logger.info("Hanging up call")

        try:
            self.telephone.hangup()
        except Exception as exc:
            logger.error(f"Failed to hang up: {exc}")
            raise

    def reject(self, identity: RNS.Identity = None):
        """
        Reject incoming call.

        Args:
            identity: RNS Identity to reject (optional)
        """
        if identity:
            identity_hash = identity.hash.hex()
            logger.info(f"Rejecting call from {identity_hash[:16]}...")
        else:
            logger.info("Rejecting call")

        try:
            self.telephone.reject(identity)
        except Exception as exc:
            logger.error(f"Failed to reject call: {exc}")
            raise

    def announce(self):
        """
        Announce this telephone service to the network.
        This makes the telephone discoverable for incoming calls.
        """
        logger.info("Manually announcing telephone service")
        self.telephone.announce()

    def switch_profile(self, profile: int):
        """
        Switch codec profile during active call.

        Args:
            profile: New LXST Profile to use (from Profiles class)
        """
        logger.info(f"Switching to profile {profile:02x}")

        try:
            self.telephone.switch_profile(profile)
            self.config.set("codec", "default_profile", profile)
        except Exception as exc:
            logger.error(f"Failed to switch profile: {exc}")
            raise

    def _on_ringing(self, identity: RNS.Identity):
        """Called when incoming call is ringing."""
        identity_hash = identity.hash.hex()
        logger.info(f"Incoming call from {identity_hash[:16]}...")
        self.call_ringing.emit(identity, identity_hash)

    def _on_established(self, identity: RNS.Identity):
        """Called when call is established."""
        identity_hash = identity.hash.hex()
        logger.info(f"Call established with {identity_hash[:16]}...")
        self.call_established.emit(identity_hash)

    def _on_ended(self, identity: RNS.Identity):
        """Called when call ends."""
        if identity:
            identity_hash = identity.hash.hex()
            logger.info(f"Call ended with {identity_hash[:16]}...")
            self.call_ended.emit(identity_hash)
        else:
            logger.info("Call ended")
            self.call_ended.emit("")

    def _on_busy(self, identity: RNS.Identity):
        """Called when remote peer is busy."""
        identity_hash = identity.hash.hex()
        logger.info(f"Peer busy: {identity_hash[:16]}...")
        self.call_busy.emit(identity_hash)

    def _on_rejected(self, identity: RNS.Identity):
        """Called when call is rejected by remote peer."""
        identity_hash = identity.hash.hex()
        logger.info(f"Call rejected by {identity_hash[:16]}...")
        self.call_rejected.emit(identity_hash)

    def received_announce(self, destination_hash, announced_identity, app_data):
        """
        Called when an LXST telephony announce is received.

        Args:
            destination_hash: The LXST destination hash (bytes)
            announced_identity: The RNS.Identity of the announcing peer
            app_data: Application data (unused for LXST)
        """
        if announced_identity:
            identity_hash = announced_identity.hash.hex()
            dest_hash_hex = destination_hash.hex()

            try:
                RNS.Identity.remember(
                    packet_hash=destination_hash,
                    destination_hash=destination_hash,
                    public_key=announced_identity.get_public_key(),
                    app_data=app_data,
                )
                logger.debug(
                    f"Remembered identity for LXST peer {identity_hash[:16]}..."
                )
            except Exception as exc:
                logger.warning(f"Could not remember identity: {exc}")

            logger.debug(
                f"Discovered LXST phone: {identity_hash[:16]}... (dest: {dest_hash_hex[:16]}...)"
            )
            self.peer_announced.emit(identity_hash, dest_hash_hex)

    @property
    def is_in_call(self) -> bool:
        """Check if currently in a call."""
        return self.telephone.call_status >= Signalling.STATUS_RINGING

    @property
    def active_profile(self) -> int:
        """Get current active profile."""
        return self.telephone.active_profile

    @property
    def call_status(self) -> int:
        """Get current call status (from Signalling constants)."""
        return self.telephone.call_status

    @property
    def remote_identity(self) -> RNS.Identity:
        """Get remote identity of current/last call."""
        return self.telephone.remote_identity

    def shutdown(self):
        """Clean shutdown of telephone."""
        logger.info("Shutting down telephone")
        try:
            if self.is_in_call:
                self.hangup()
        except Exception as exc:
            logger.error(f"Error during shutdown: {exc}")

    def get_sas_code(self) -> str | None:
        """
        Get SAS (Short Authentication String) code for active call.

        Returns a human-readable code derived from the RNS link salt that both
        parties can verify to ensure no man-in-the-middle attack.

        Returns:
            SAS code string (e.g., "49-14-71-02") or None if no active call
        """
        if not self.is_in_call:
            logger.warning("Cannot get SAS: no active call")
            return None

        try:
            if (
                not hasattr(self.telephone, "active_call")
                or not self.telephone.active_call
            ):
                logger.warning("No active call object available")
                return None

            active_call = self.telephone.active_call

            if not hasattr(active_call, "status"):
                logger.warning("Active call has no status attribute")
                return None

            if active_call.status != RNS.Link.ACTIVE:
                logger.warning(f"Link is not active (status: {active_call.status})")
                return None

            if not hasattr(active_call, "get_salt"):
                logger.warning("Active call link has no get_salt method")
                return None

            salt = active_call.get_salt()
            if not salt:
                logger.warning("Could not get link salt (returned None or empty)")
                return None

            sas_code = self._generate_sas_from_salt(salt)
            logger.debug(f"Generated SAS code: {sas_code}")
            return sas_code

        except Exception as exc:
            logger.error(f"Error getting SAS code: {exc}", exc_info=True)
            return None

    def _generate_sas_from_salt(self, salt_bytes: bytes, num_groups: int = 4) -> str:
        """
        Generate a human-readable SAS code from link salt.

        Args:
            salt_bytes: The link salt bytes
            num_groups: Number of 2-digit groups to generate (default 4)

        Returns:
            SAS code string like "49-14-71-02"
        """
        hash_digest = hashlib.sha256(salt_bytes).digest()

        sas_nums = []
        for i in range(num_groups):
            byte_val = hash_digest[i]
            sas_nums.append(f"{byte_val % 100:02d}")

        return "-".join(sas_nums)
