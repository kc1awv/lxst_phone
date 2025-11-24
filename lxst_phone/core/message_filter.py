from __future__ import annotations

import time
from typing import Optional, Tuple

from lxst_phone.core.signaling import CallMessage

Decision = Tuple[bool, str]


class CallMessageFilter:
    """
    Stateless-ish helper that enforces basic validation and duplicate suppression
    for signaling messages before they are handed to the UI/state machine.
    """

    def __init__(self, local_id: str, dupe_window_sec: float = 1.0) -> None:
        self.local_id = local_id
        self.dupe_window_sec = dupe_window_sec
        self._recent: dict[tuple[str, str], float] = {}

    def evaluate(self, msg: CallMessage, current_call_id: Optional[str]) -> Decision:
        """
        Returns (allowed, reason).
        Reasons (when allowed is False):
        - not_for_us
        - duplicate
        - unknown_call_idle
        - foreign_call
        """

        if msg.msg_type == "PRESENCE_ANNOUNCE":
            return True, "presence_announce"

        if msg.to_id != self.local_id:
            return False, "not_for_us"

        now = time.time()
        key = (msg.call_id, msg.msg_type)
        last_seen = self._recent.get(key)
        if last_seen and (now - last_seen) < self.dupe_window_sec:
            return False, "duplicate"
        self._recent[key] = now

        if msg.msg_type != "CALL_INVITE":
            if current_call_id is None:
                return False, "unknown_call_idle"
            if current_call_id != msg.call_id:
                return False, "foreign_call"

        return True, "ok"
