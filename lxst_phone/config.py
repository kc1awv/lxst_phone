"""
Configuration management for LXST Phone.

Handles loading/saving user preferences to a JSON config file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from lxst_phone.logging_config import get_logger

logger = get_logger("config")


class Config:
    """
    Application configuration with persistent storage.
    """

    DEFAULT_CONFIG = {
        "audio": {
            "input_device": None,  # None = system default
            "output_device": None,
            "enabled": True,
        },
        "codec": {
            "type": "opus",  # "opus" or "codec2"
            "sample_rate": 48000,
            "frame_ms": 20,
            "channels": 1,
            "complexity": 10,  # Opus complexity 0-10 (higher = better quality, more CPU)
            "opus_bitrate": 24000,  # Opus bitrate in bps (8000-128000, default 24000)
            "codec2_mode": 3200,  # Codec2 mode: 3200, 2400, 1600, 1400, 1300, 1200, 700C (bps)
        },
        "network": {
            "target_jitter_ms": 60,  # Jitter buffer delay
            "adaptive_jitter": False,  # Future: adaptive jitter buffer
            "announce_on_start": True,  # Send presence announcement on startup
            "announce_period_minutes": 5,  # How often to send presence announcements
        },
        "ui": {
            "window_width": 620,
            "window_height": 550,
            "last_remote_id": "",  # Remember last called number
            "display_name": "",  # User's display name for announcements
        },
        "security": {
            "verify_sas": True,  # Prompt for SAS verification on new links
            "auto_accept_known": False,  # Auto-accept calls from verified contacts
            "max_calls_per_minute": 5,  # Rate limit: max calls per peer per minute
            "max_calls_per_hour": 20,  # Rate limit: max calls per peer per hour
        },
    }

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """
        Initialize configuration.

        Args:
            config_path: Path to config file. If None, uses ~/.lxst_phone/config.json
        """
        if config_path is None:
            config_dir = Path.home() / ".lxst_phone"
            config_dir.mkdir(exist_ok=True)
            config_path = config_dir / "config.json"

        self.config_path = config_path
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from file, or use defaults if file doesn't exist."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    loaded = json.load(f)
                self._data = self._merge_defaults(loaded)
            except Exception as exc:
                logger.error(f"Failed to load config from {self.config_path}: {exc}")
                logger.warning("Using default configuration")
                self._data = self.DEFAULT_CONFIG.copy()
        else:
            self._data = self.DEFAULT_CONFIG.copy()

    def save(self) -> None:
        """Save current configuration to file."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save config to {self.config_path}: {exc}")

    def _merge_defaults(self, loaded: dict[str, Any]) -> dict[str, Any]:
        """Merge loaded config with defaults to handle missing keys."""
        result = self.DEFAULT_CONFIG.copy()
        for section_key, section_defaults in self.DEFAULT_CONFIG.items():
            if section_key in loaded and isinstance(section_defaults, dict):
                merged_section = section_defaults.copy()
                merged_section.update(loaded[section_key])
                result[section_key] = merged_section
            elif section_key in loaded:
                result[section_key] = loaded[section_key]
        return result

    def get(self, section: str, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._data.get(section, {}).get(key, default)

    def set(self, section: str, key: str, value: Any) -> None:
        """Set a configuration value."""
        if section not in self._data:
            self._data[section] = {}
        self._data[section][key] = value

    def get_section(self, section: str) -> dict[str, Any]:
        """Get an entire configuration section."""
        return self._data.get(section, {}).copy()

    @property
    def audio_input_device(self) -> Optional[int]:
        return self.get("audio", "input_device")

    @audio_input_device.setter
    def audio_input_device(self, value: Optional[int]) -> None:
        self.set("audio", "input_device", value)

    @property
    def audio_output_device(self) -> Optional[int]:
        return self.get("audio", "output_device")

    @audio_output_device.setter
    def audio_output_device(self, value: Optional[int]) -> None:
        self.set("audio", "output_device", value)

    @property
    def audio_enabled(self) -> bool:
        return self.get("audio", "enabled", True)

    @audio_enabled.setter
    def audio_enabled(self, value: bool) -> None:
        self.set("audio", "enabled", value)

    @property
    def target_jitter_ms(self) -> int:
        return self.get("network", "target_jitter_ms", 60)

    @target_jitter_ms.setter
    def target_jitter_ms(self, value: int) -> None:
        self.set("network", "target_jitter_ms", value)

    @property
    def codec_type(self) -> str:
        return self.get("codec", "type", "opus")

    @codec_type.setter
    def codec_type(self, value: str) -> None:
        self.set("codec", "type", value)

    @property
    def opus_bitrate(self) -> int:
        return self.get("codec", "opus_bitrate", 24000)

    @opus_bitrate.setter
    def opus_bitrate(self, value: int) -> None:
        self.set("codec", "opus_bitrate", value)

    @property
    def codec2_mode(self) -> int:
        return self.get("codec", "codec2_mode", 3200)

    @codec2_mode.setter
    def codec2_mode(self, value: int) -> None:
        self.set("codec", "codec2_mode", value)

    @property
    def opus_complexity(self) -> int:
        return self.get("codec", "complexity", 10)

    @opus_complexity.setter
    def opus_complexity(self, value: int) -> None:
        self.set("codec", "complexity", value)

    @property
    def window_geometry(self) -> tuple[int, int]:
        """Get window (width, height)."""
        w = self.get("ui", "window_width", 620)
        h = self.get("ui", "window_height", 550)
        return (w, h)

    @window_geometry.setter
    def window_geometry(self, value: tuple[int, int]) -> None:
        """Set window (width, height)."""
        w, h = value
        self.set("ui", "window_width", w)
        self.set("ui", "window_height", h)

    @property
    def last_remote_id(self) -> str:
        return self.get("ui", "last_remote_id", "")

    @last_remote_id.setter
    def last_remote_id(self, value: str) -> None:
        self.set("ui", "last_remote_id", value)

    @property
    def announce_on_start(self) -> bool:
        return self.get("network", "announce_on_start", True)

    @announce_on_start.setter
    def announce_on_start(self, value: bool) -> None:
        self.set("network", "announce_on_start", value)

    @property
    def announce_period_minutes(self) -> int:
        return self.get("network", "announce_period_minutes", 5)

    @announce_period_minutes.setter
    def announce_period_minutes(self, value: int) -> None:
        self.set("network", "announce_period_minutes", value)

    @property
    def display_name(self) -> str:
        return self.get("ui", "display_name", "")

    @display_name.setter
    def display_name(self, value: str) -> None:
        self.set("ui", "display_name", value)

    @property
    def max_calls_per_minute(self) -> int:
        return self.get("security", "max_calls_per_minute", 5)

    @max_calls_per_minute.setter
    def max_calls_per_minute(self, value: int) -> None:
        self.set("security", "max_calls_per_minute", value)

    @property
    def max_calls_per_hour(self) -> int:
        return self.get("security", "max_calls_per_hour", 20)

    @max_calls_per_hour.setter
    def max_calls_per_hour(self, value: int) -> None:
        self.set("security", "max_calls_per_hour", value)
