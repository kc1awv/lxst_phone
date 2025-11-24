"""
Call history tracking for LXST Phone.

Maintains a persistent log of incoming and outgoing calls.
Call history is encrypted using the local identity for privacy.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import RNS
except ImportError:
    RNS = None  # type: ignore

from lxst_phone.logging_config import get_logger

logger = get_logger("call_history")


@dataclass
class CallRecord:
    """Represents a single call history entry."""

    timestamp: str  # ISO format datetime
    direction: str  # "incoming" or "outgoing"
    peer_id: str
    display_name: str
    duration_sec: int
    answered: bool
    call_id: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CallRecord:
        """Create CallRecord from dictionary."""
        return cls(**data)


class CallHistory:
    """Manages persistent call history storage with encryption."""

    def __init__(self, storage_path: Optional[Path] = None, identity=None):  # type: ignore
        """
        Initialize call history.

        Args:
            storage_path: Path to history JSON file. If None, uses ~/.lxst_phone/call_history.json
            identity: RNS.Identity for encryption. If provided, call history is encrypted.
        """
        if storage_path is None:
            storage_dir = Path.home() / ".lxst_phone"
            storage_dir.mkdir(exist_ok=True)
            storage_path = storage_dir / "call_history.json"

        self.storage_path = storage_path
        self.identity = identity  # For encryption
        self.calls: list[CallRecord] = []
        self.max_entries = 1000  # Keep last 1000 calls

    def load(self) -> None:
        """Load call history from storage file (supports both encrypted and plain text)."""
        if not self.storage_path.exists():
            logger.debug("No call history file found, starting fresh")
            return

        try:
            with open(self.storage_path, "r") as f:
                file_data = json.load(f)

            if not isinstance(file_data, dict):
                logger.error(
                    f"Invalid history file format: expected dict, got {type(file_data).__name__}"
                )
                return

            if (
                "encrypted" in file_data
                and file_data.get("encrypted")
                and self.identity
            ):
                try:
                    encrypted_b64 = file_data.get("data")
                    if not encrypted_b64:
                        logger.error("Encrypted file missing 'data' field")
                        return

                    encrypted_bytes = base64.b64decode(encrypted_b64)
                    decrypted_bytes = self.identity.decrypt(encrypted_bytes)
                    decrypted_str = decrypted_bytes.decode("utf-8")
                    data = json.loads(decrypted_str)

                    logger.info("Successfully decrypted call history")
                except Exception as exc:
                    logger.error(f"Failed to decrypt call history: {exc}")
                    return
            else:
                data = file_data
                if self.identity:
                    logger.warning(
                        "Call history file is not encrypted. It will be encrypted on next save."
                    )

            if "calls" not in data:
                logger.error("Invalid history file: missing 'calls' key")
                return

            if not isinstance(data["calls"], list):
                logger.error(
                    f"Invalid calls format: expected list, got {type(data['calls']).__name__}"
                )
                return

            for call_data in data["calls"]:
                try:
                    record = CallRecord.from_dict(call_data)
                    self.calls.append(record)
                except Exception as exc:
                    logger.warning(f"Skipping invalid call record: {exc}")
                    continue

            logger.info(
                f"Loaded {len(self.calls)} call records from {self.storage_path}"
            )

        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse history file {self.storage_path}: {exc}")
        except Exception as exc:
            logger.error(f"Failed to load call history from {self.storage_path}: {exc}")

    def save(self) -> None:
        """Save call history to storage file (encrypted if identity provided)."""
        try:
            if len(self.calls) > self.max_entries:
                self.calls = self.calls[-self.max_entries :]

            data = {
                "version": 1,
                "calls": [call.to_dict() for call in self.calls],
            }

            if self.identity:
                json_str = json.dumps(data)
                encrypted_bytes = self.identity.encrypt(json_str.encode("utf-8"))
                encrypted_b64 = base64.b64encode(encrypted_bytes).decode("ascii")

                file_data = {
                    "encrypted": True,
                    "version": 1,
                    "data": encrypted_b64,
                }
            else:
                file_data = data

            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.storage_path, "w") as f:
                json.dump(file_data, f, indent=2)

            logger.debug(f"Saved {len(self.calls)} call records to {self.storage_path}")

        except Exception as exc:
            logger.error(f"Failed to save call history to {self.storage_path}: {exc}")

    def add_call(
        self,
        direction: str,
        peer_id: str,
        display_name: str,
        duration_sec: int,
        answered: bool,
        call_id: str,
    ) -> None:
        """
        Add a call to the history.

        Args:
            direction: "incoming" or "outgoing"
            peer_id: Remote peer's node ID
            display_name: Remote peer's display name
            duration_sec: Call duration in seconds
            answered: Whether the call was answered
            call_id: Unique call ID
        """
        record = CallRecord(
            timestamp=datetime.now().isoformat(),
            direction=direction,
            peer_id=peer_id,
            display_name=display_name,
            duration_sec=duration_sec,
            answered=answered,
            call_id=call_id,
        )

        self.calls.append(record)
        self.save()

        logger.info(
            f"Added {direction} call to history: "
            f"peer={peer_id[:16]}..., answered={answered}, duration={duration_sec}s"
        )

    def get_recent_calls(self, limit: int = 50) -> list[CallRecord]:
        """
        Get most recent calls.

        Args:
            limit: Maximum number of calls to return

        Returns:
            List of CallRecord objects, sorted by timestamp (newest first)
        """
        sorted_calls = sorted(self.calls, key=lambda c: c.timestamp, reverse=True)
        return sorted_calls[:limit]

    def get_calls_for_peer(self, peer_id: str, limit: int = 10) -> list[CallRecord]:
        """
        Get call history for a specific peer.

        Args:
            peer_id: Peer's node ID
            limit: Maximum number of calls to return

        Returns:
            List of CallRecord objects for this peer, sorted by timestamp (newest first)
        """
        peer_calls = [call for call in self.calls if call.peer_id == peer_id]
        sorted_calls = sorted(peer_calls, key=lambda c: c.timestamp, reverse=True)
        return sorted_calls[:limit]

    def get_statistics(self) -> dict:
        """
        Get call statistics.

        Returns:
            Dictionary with statistics (total calls, answered calls, total duration, etc.)
        """
        total_calls = len(self.calls)
        answered_calls = sum(1 for call in self.calls if call.answered)
        total_duration = sum(call.duration_sec for call in self.calls)
        incoming_calls = sum(1 for call in self.calls if call.direction == "incoming")
        outgoing_calls = sum(1 for call in self.calls if call.direction == "outgoing")

        return {
            "total_calls": total_calls,
            "answered_calls": answered_calls,
            "missed_calls": total_calls - answered_calls,
            "total_duration_sec": total_duration,
            "incoming_calls": incoming_calls,
            "outgoing_calls": outgoing_calls,
        }

    def clear_history(self) -> None:
        """Clear all call history."""
        self.calls.clear()
        self.save()
        logger.info("Call history cleared")
