from dataclasses import dataclass
from typing import Literal, Dict, Any, Optional
import time
import uuid
import base64


CallMessageType = Literal[
    "CALL_INVITE",
    "CALL_RINGING",
    "CALL_ACCEPT",
    "CALL_REJECT",
    "CALL_END",
    "PRESENCE_ANNOUNCE",  # Discovery message broadcast on PLAIN
]


@dataclass
class CallMessage:
    msg_type: CallMessageType
    call_id: str
    from_id: str
    to_id: str
    display_name: str | None = None
    call_dest: str | None = None
    call_identity_key: str | None = None
    codec_type: str | None = None  # "opus" or "codec2"
    codec_bitrate: int | None = None  # Normalized bitrate in bps
    timestamp: float = 0.0

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "type": self.msg_type,
            "call_id": self.call_id,
            "from": self.from_id,
            "to": self.to_id,
        }

        if self.display_name:
            payload["display_name"] = self.display_name
        if self.call_dest:
            payload["call_dest"] = self.call_dest
        if self.call_identity_key:
            payload["call_identity_key"] = self.call_identity_key
        if self.codec_type:
            payload["codec_type"] = self.codec_type
        if self.codec_bitrate is not None:
            payload["codec_bitrate"] = self.codec_bitrate
        if self.timestamp:
            payload["timestamp"] = self.timestamp

        return payload

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "CallMessage":
        # Support both old media_dest and new call_dest naming for backwards compatibility
        call_dest = payload.get("call_dest") or payload.get("media_dest")
        call_identity_key = payload.get("call_identity_key") or payload.get("media_identity_key")
        
        return cls(
            msg_type=payload["type"],
            call_id=payload["call_id"],
            from_id=payload["from"],
            to_id=payload["to"],
            display_name=payload.get("display_name"),
            call_dest=call_dest,
            call_identity_key=call_identity_key,
            codec_type=payload.get("codec_type"),
            codec_bitrate=payload.get("codec_bitrate"),
            timestamp=payload.get("timestamp", 0.0),
        )


def new_call_id() -> str:
    return str(uuid.uuid4())


def normalize_codec_bitrate(codec_type: str, bitrate_or_mode: int) -> int:
    """
    Normalize codec bitrate to a common scale for comparison.

    For Opus: bitrate is already in bps
    For Codec2: mode IS the bitrate in bps

    Returns bitrate in bps.
    """
    if codec_type == "opus":
        return bitrate_or_mode
    elif codec_type == "codec2":
        return bitrate_or_mode  # Mode is the bitrate
    else:
        return 24000  # Default fallback


def negotiate_codec(
    local_codec: str,
    local_bitrate: int,
    remote_codec: str | None,
    remote_bitrate: int | None,
) -> tuple[str, int]:
    """
    Negotiate codec settings between two peers.

    Returns (codec_type, bitrate) to use for the call.

    Rules:
    1. If remote doesn't specify, use local settings
    2. Codec2 takes priority over Opus (lower bandwidth)
    3. Within same codec, use lower bitrate
    """
    if remote_codec is None or remote_bitrate is None:
        return (local_codec, local_bitrate)

    local_bps = normalize_codec_bitrate(local_codec, local_bitrate)
    remote_bps = normalize_codec_bitrate(remote_codec, remote_bitrate)

    if local_codec == "codec2" and remote_codec == "opus":
        return (local_codec, local_bitrate)
    elif remote_codec == "codec2" and local_codec == "opus":
        return (remote_codec, remote_bitrate)

    if local_bps <= remote_bps:
        return (local_codec, local_bitrate)
    else:
        return (remote_codec, remote_bitrate)


def build_invite(
    from_id: str,
    to_id: str,
    display_name: str | None = None,
    call_dest: str | None = None,
    call_identity_key: str | None = None,
    codec_type: str | None = None,
    codec_bitrate: int | None = None,
    call_id: Optional[str] = None,
) -> CallMessage:
    return CallMessage(
        msg_type="CALL_INVITE",
        call_id=call_id or new_call_id(),
        from_id=from_id,
        to_id=to_id,
        display_name=display_name,
        call_dest=call_dest,
        call_identity_key=call_identity_key,
        codec_type=codec_type,
        codec_bitrate=codec_bitrate,
        timestamp=time.time(),
    )


def build_accept(
    from_id: str,
    to_id: str,
    call_id: str,
    call_dest: str | None = None,
    call_identity_key: str | None = None,
    codec_type: str | None = None,
    codec_bitrate: int | None = None,
) -> CallMessage:
    return CallMessage(
        msg_type="CALL_ACCEPT",
        call_id=call_id,
        from_id=from_id,
        to_id=to_id,
        call_dest=call_dest,
        call_identity_key=call_identity_key,
        codec_type=codec_type,
        codec_bitrate=codec_bitrate,
        timestamp=time.time(),
    )


def build_reject(from_id: str, to_id: str, call_id: str) -> CallMessage:
    return CallMessage(
        msg_type="CALL_REJECT",
        call_id=call_id,
        from_id=from_id,
        to_id=to_id,
        timestamp=time.time(),
    )


def build_end(from_id: str, to_id: str, call_id: str) -> CallMessage:
    return CallMessage(
        msg_type="CALL_END",
        call_id=call_id,
        from_id=from_id,
        to_id=to_id,
        timestamp=time.time(),
    )


def build_announce(
    from_id: str,
    display_name: str | None = None,
    call_dest: str | None = None,
    call_identity_key: str | None = None,
) -> CallMessage:
    """Build a presence announcement for discovery."""
    return CallMessage(
        msg_type="PRESENCE_ANNOUNCE",
        call_id="",  # Not call-specific
        from_id=from_id,
        to_id="",  # Broadcast to all
        display_name=display_name,
        call_dest=call_dest,
        call_identity_key=call_identity_key,
        timestamp=time.time(),
    )
