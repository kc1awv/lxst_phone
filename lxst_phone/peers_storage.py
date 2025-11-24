"""
Persistent storage for discovered peers.

Handles loading and saving peer information to a JSON file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from datetime import datetime

from lxst_phone.logging_config import get_logger

logger = get_logger("peers")


class PeerRecord:
    """Represents a stored peer record."""

    def __init__(
        self,
        node_id: str,
        display_name: str = "Unknown",
        last_seen: datetime | None = None,
        announce_count: int = 1,
        verified: bool = False,
        blocked: bool = False,
    ):
        self.node_id = node_id
        self.display_name = display_name
        self.last_seen = last_seen or datetime.now()
        self.announce_count = announce_count
        self.verified = verified  # Has SAS been verified?
        self.blocked = blocked  # Is this peer blocked?

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON storage."""
        return {
            "node_id": self.node_id,
            "display_name": self.display_name,
            "last_seen": self.last_seen.isoformat(),
            "announce_count": self.announce_count,
            "verified": self.verified,
            "blocked": self.blocked,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeerRecord:
        """Deserialize from dictionary."""
        return cls(
            node_id=data["node_id"],
            display_name=data.get("display_name", "Unknown"),
            last_seen=datetime.fromisoformat(data["last_seen"]),
            announce_count=data.get("announce_count", 1),
            verified=data.get("verified", False),
            blocked=data.get("blocked", False),
        )


class PeersStorage:
    """Manages persistent storage of discovered peers."""

    def __init__(self, storage_path: Path | None = None):
        """
        Initialize peers storage.

        Args:
            storage_path: Path to peers JSON file. If None, uses ~/.lxst_phone/peers.json
        """
        if storage_path is None:
            storage_dir = Path.home() / ".lxst_phone"
            storage_dir.mkdir(exist_ok=True)
            storage_path = storage_dir / "peers.json"

        self.storage_path = storage_path
        self.peers: dict[str, PeerRecord] = {}

    def load(self) -> None:
        """Load peers from storage file."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r") as f:
                data = json.load(f)

            if not isinstance(data, dict):
                logger.error(
                    f"Invalid peers file format: expected dict, got {type(data).__name__}"
                )
                return

            if "peers" not in data:
                logger.error("Invalid peers file: missing 'peers' key")
                return

            if not isinstance(data["peers"], list):
                logger.error(
                    f"Invalid peers format: expected list, got {type(data['peers']).__name__}"
                )
                return

            temp_peers: dict[str, PeerRecord] = {}
            for peer_data in data["peers"]:
                try:
                    if not isinstance(peer_data, dict):
                        logger.warning(f"Skipping invalid peer record: {peer_data}")
                        continue

                    record = PeerRecord.from_dict(peer_data)
                    temp_peers[record.node_id] = record
                except (KeyError, ValueError, TypeError) as exc:
                    logger.warning(f"Failed to load peer record: {exc}")
                    continue

            self.peers = temp_peers
            logger.info(f"Loaded {len(self.peers)} peers from {self.storage_path}")
        except json.JSONDecodeError as exc:
            logger.error(f"Failed to parse peers file {self.storage_path}: {exc}")
        except (OSError, IOError) as exc:
            logger.error(f"Failed to read peers file {self.storage_path}: {exc}")
        except Exception as exc:
            logger.error(
                f"Unexpected error loading peers from {self.storage_path}: {exc}"
            )

    def save(self) -> None:
        """Save peers to storage file."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)

            data = {"peers": [peer.to_dict() for peer in self.peers.values()]}

            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved {len(self.peers)} peers to {self.storage_path}")
        except (OSError, IOError) as exc:
            logger.error(f"Failed to write peers to {self.storage_path}: {exc}")
        except Exception as exc:
            logger.error(f"Unexpected error saving peers to {self.storage_path}: {exc}")

    def add_or_update(
        self, node_id: str, display_name: str | None = None
    ) -> PeerRecord:
        """
        Add a new peer or update existing peer.

        Args:
            node_id: The peer's node ID
            display_name: The peer's display name (optional)

        Returns:
            The updated or created PeerRecord
        """
        if node_id in self.peers:
            record = self.peers[node_id]
            if display_name:
                record.display_name = display_name
            record.last_seen = datetime.now()
            record.announce_count += 1
        else:
            record = PeerRecord(
                node_id=node_id,
                display_name=display_name or "Unknown",
                last_seen=datetime.now(),
                announce_count=1,
            )
            self.peers[node_id] = record

        return record

    def get(self, node_id: str) -> PeerRecord | None:
        """Get a peer record by node ID."""
        return self.peers.get(node_id)

    def mark_verified(self, node_id: str) -> None:
        """Mark a peer as verified (SAS confirmed)."""
        if node_id in self.peers:
            self.peers[node_id].verified = True
            self.save()

    def mark_blocked(self, node_id: str) -> None:
        """Block a peer (auto-reject calls)."""
        if node_id in self.peers:
            self.peers[node_id].blocked = True
            self.save()

    def unblock(self, node_id: str) -> None:
        """Unblock a previously blocked peer."""
        if node_id in self.peers:
            self.peers[node_id].blocked = False
            self.save()

    def is_blocked(self, node_id: str) -> bool:
        """Check if a peer is blocked."""
        peer = self.peers.get(node_id)
        return peer.blocked if peer else False

    def is_verified(self, node_id: str) -> bool:
        """Check if a peer has been verified."""
        peer = self.peers.get(node_id)
        return peer.verified if peer else False

    def get_all(self) -> list[PeerRecord]:
        """Get all peer records."""
        return list(self.peers.values())

    def remove(self, node_id: str) -> None:
        """Remove a peer from storage."""
        if node_id in self.peers:
            del self.peers[node_id]

    def clear(self) -> None:
        """Clear all peers."""
        self.peers.clear()
