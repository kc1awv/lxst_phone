from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Callable

from lxst_phone.core.signaling import new_call_id


class CallPhase(Enum):
    IDLE = auto()
    OUTGOING_CALL = auto()
    RINGING = auto()
    INCOMING_CALL = auto()
    IN_CALL = auto()
    ENDED = auto()


@dataclass
class CallInfo:
    call_id: str
    local_id: str
    remote_id: str
    display_name: Optional[str] = None
    initiated_by_local: bool = False
    remote_media_dest: Optional[str] = None
    remote_identity_key: Optional[str] = None
    negotiated_codec_type: Optional[str] = None
    negotiated_codec_bitrate: Optional[int] = None


class CallStateMachine:
    """
    Minimal call state machine.
    This is pure logic: no networking, no audio, just state transitions.
    UI or networking code can subscribe to on_state_changed.
    """

    def __init__(self) -> None:
        self.phase: CallPhase = CallPhase.IDLE
        self.current_call: Optional[CallInfo] = None
        self.on_state_changed: Optional[
            Callable[[CallPhase, Optional[CallInfo]], None]
        ] = None

    def _set_state(self, phase: CallPhase) -> None:
        self.phase = phase
        if self.on_state_changed:
            self.on_state_changed(self.phase, self.current_call)

    def start_outgoing_call(
        self, local_id: str, remote_id: str, call_id: Optional[str] = None
    ) -> CallInfo:
        if self.phase not in (CallPhase.IDLE, CallPhase.ENDED):
            raise RuntimeError("Cannot start a new call while another call is active.")

        call = CallInfo(
            call_id=call_id or new_call_id(),
            local_id=local_id,
            remote_id=remote_id,
            initiated_by_local=True,
        )
        self.current_call = call
        self._set_state(CallPhase.OUTGOING_CALL)
        return call

    def mark_ringing(self) -> None:
        """Mark outgoing call as ringing (remote is being alerted)."""
        if self.phase == CallPhase.OUTGOING_CALL:
            self._set_state(CallPhase.RINGING)
        elif self.phase == CallPhase.RINGING:
            pass

    def receive_incoming_invite(self, call: CallInfo) -> bool:
        if self.phase not in (CallPhase.IDLE, CallPhase.ENDED):
            return False
        self.current_call = call
        self._set_state(CallPhase.INCOMING_CALL)
        return True

    def accept_current_call(self) -> None:
        if self.phase != CallPhase.INCOMING_CALL or self.current_call is None:
            raise RuntimeError("No incoming call to accept.")
        self._set_state(CallPhase.IN_CALL)

    def reject_current_call(self) -> None:
        if self.phase != CallPhase.INCOMING_CALL or self.current_call is None:
            raise RuntimeError("No incoming call to reject.")
        self._set_state(CallPhase.ENDED)
        self.current_call = None
        self._set_state(CallPhase.IDLE)

    def mark_remote_accepted(
        self,
        call_id: str,
        remote_media_dest: Optional[str] = None,
        remote_identity_key: Optional[str] = None,
    ) -> None:
        if not self.current_call or self.current_call.call_id != call_id:
            return
        if remote_media_dest:
            self.current_call.remote_media_dest = remote_media_dest
        if remote_identity_key:
            self.current_call.remote_identity_key = remote_identity_key
        self._set_state(CallPhase.IN_CALL)

    def mark_remote_rejected(self, call_id: str) -> None:
        if not self.current_call or self.current_call.call_id != call_id:
            return
        self._set_state(CallPhase.ENDED)
        self.current_call = None
        self._set_state(CallPhase.IDLE)

    def remote_ended(self, call_id: str) -> None:
        if not self.current_call or self.current_call.call_id != call_id:
            return
        self._set_state(CallPhase.ENDED)
        self.current_call = None
        self._set_state(CallPhase.IDLE)

    def end_call(self) -> None:
        if self.current_call is None:
            return
        self._set_state(CallPhase.ENDED)
        self.current_call = None
        self._set_state(CallPhase.IDLE)
