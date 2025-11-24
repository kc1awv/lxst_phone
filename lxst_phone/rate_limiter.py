"""
Rate limiting for LXST Phone.

Prevents spam calls and DoS attacks by limiting call frequency per peer.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Dict

from lxst_phone.logging_config import get_logger

logger = get_logger("rate_limiter")


class RateLimiter:
    """
    Rate limiter for incoming calls.

    Tracks call attempts per peer and enforces configurable limits.
    """

    def __init__(
        self,
        max_calls_per_minute: int = 5,
        max_calls_per_hour: int = 20,
        window_cleanup_interval: int = 300,  # Clean old entries every 5 minutes
    ):
        """
        Initialize rate limiter.

        Args:
            max_calls_per_minute: Maximum calls from a peer per minute
            max_calls_per_hour: Maximum calls from a peer per hour
            window_cleanup_interval: Seconds between cleanup of old timestamps
        """
        self.max_calls_per_minute = max_calls_per_minute
        self.max_calls_per_hour = max_calls_per_hour
        self.window_cleanup_interval = window_cleanup_interval

        self.call_timestamps: Dict[str, deque[float]] = {}

        self._last_cleanup = time.time()

    def is_allowed(self, peer_id: str) -> bool:
        """
        Check if a call from this peer is allowed.

        Args:
            peer_id: Remote peer's node ID

        Returns:
            True if call is allowed, False if rate limit exceeded
        """
        now = time.time()

        if now - self._last_cleanup > self.window_cleanup_interval:
            self._cleanup_old_entries(now)

        if peer_id not in self.call_timestamps:
            self.call_timestamps[peer_id] = deque()

        timestamps = self.call_timestamps[peer_id]

        minute_cutoff = now - 60.0
        hour_cutoff = now - 3600.0

        while timestamps and timestamps[0] < hour_cutoff:
            timestamps.popleft()

        calls_in_minute = sum(1 for ts in timestamps if ts >= minute_cutoff)
        calls_in_hour = len(timestamps)

        if calls_in_minute >= self.max_calls_per_minute:
            logger.warning(
                f"Rate limit exceeded for {peer_id[:16]}...: "
                f"{calls_in_minute} calls in last minute (limit: {self.max_calls_per_minute})"
            )
            return False

        if calls_in_hour >= self.max_calls_per_hour:
            logger.warning(
                f"Rate limit exceeded for {peer_id[:16]}...: "
                f"{calls_in_hour} calls in last hour (limit: {self.max_calls_per_hour})"
            )
            return False

        timestamps.append(now)

        return True

    def _cleanup_old_entries(self, now: float) -> None:
        """
        Remove peers that haven't called in over an hour.

        Args:
            now: Current timestamp
        """
        hour_cutoff = now - 3600.0
        peers_to_remove = []

        for peer_id, timestamps in self.call_timestamps.items():
            while timestamps and timestamps[0] < hour_cutoff:
                timestamps.popleft()

            if not timestamps:
                peers_to_remove.append(peer_id)

        for peer_id in peers_to_remove:
            del self.call_timestamps[peer_id]

        if peers_to_remove:
            logger.debug(
                f"Cleaned up {len(peers_to_remove)} inactive peers from rate limiter"
            )

        self._last_cleanup = now

    def reset_peer(self, peer_id: str) -> None:
        """
        Reset rate limiting for a specific peer.

        Useful for removing limits after blocking a peer or for testing.

        Args:
            peer_id: Peer's node ID
        """
        if peer_id in self.call_timestamps:
            del self.call_timestamps[peer_id]
            logger.info(f"Reset rate limits for {peer_id[:16]}...")

    def get_peer_stats(self, peer_id: str) -> dict:
        """
        Get rate limiting statistics for a peer.

        Args:
            peer_id: Peer's node ID

        Returns:
            Dictionary with call counts in various time windows
        """
        now = time.time()

        if peer_id not in self.call_timestamps:
            return {
                "calls_last_minute": 0,
                "calls_last_hour": 0,
                "total_calls": 0,
            }

        timestamps = self.call_timestamps[peer_id]
        minute_cutoff = now - 60.0

        return {
            "calls_last_minute": sum(1 for ts in timestamps if ts >= minute_cutoff),
            "calls_last_hour": len(timestamps),
            "total_calls": len(timestamps),
        }

    def get_all_stats(self) -> dict:
        """
        Get overall rate limiting statistics.

        Returns:
            Dictionary with aggregate statistics
        """
        return {
            "tracked_peers": len(self.call_timestamps),
            "total_calls_tracked": sum(len(ts) for ts in self.call_timestamps.values()),
        }
