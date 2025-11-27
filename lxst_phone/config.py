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
            "use_filters": True,  # Enable audio filters for better voice quality
            "filter_type": "voice",  # voice, music, none
            "bandpass_low": 300,  # Hz - lower frequency cutoff (voice optimized)
            "bandpass_high": 3400,  # Hz - upper frequency cutoff (voice optimized)
            "use_agc": True,  # Automatic Gain Control for consistent volume
            "agc_target_level": -12.0,  # dBFS - target audio level
            "agc_max_gain": 12.0,  # dB - maximum gain boost
        },
        "codec": {
            "default_profile": 0x40,  # LXST Profile (0x40 = QUALITY_MEDIUM)
        },
        "network": {
            "announce_on_start": True,  # Send presence announcement on startup
            "announce_period_minutes": 5,  # How often to send presence announcements
        },
        "ui": {
            "window_width": 620,
            "window_height": 550,
            "last_remote_id": "",  # Remember last called number
            "display_name": "",  # User's display name for announcements
        },
        "security": {},
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
    def default_profile(self) -> int:
        """Get default LXST profile."""
        return self.get("codec", "default_profile", 0x40)

    @default_profile.setter
    def default_profile(self, value: int) -> None:
        """Set default LXST profile."""
        self.set("codec", "default_profile", value)

    @property
    def window_geometry(self) -> tuple[int, int]:
        """Get window (width, height)."""
        w = self.get("ui", "window_width", 620)
        h = self.get("ui", "window_height", 550)
        return (w, h)

    @property
    def use_audio_filters(self) -> bool:
        """Get whether to use audio filters."""
        return self.get("audio", "use_filters", True)

    @use_audio_filters.setter
    def use_audio_filters(self, value: bool) -> None:
        """Set whether to use audio filters."""
        self.set("audio", "use_filters", value)

    @property
    def filter_type(self) -> str:
        """Get filter type (voice, music, none)."""
        return self.get("audio", "filter_type", "voice")

    @filter_type.setter
    def filter_type(self, value: str) -> None:
        """Set filter type."""
        if value not in ["voice", "music", "none"]:
            raise ValueError(f"Invalid filter type: {value}")
        self.set("audio", "filter_type", value)

    @property
    def use_agc(self) -> bool:
        """Get whether to use Automatic Gain Control."""
        return self.get("audio", "use_agc", True)

    @use_agc.setter
    def use_agc(self, value: bool) -> None:
        """Set whether to use Automatic Gain Control."""
        self.set("audio", "use_agc", value)

    @property
    def bandpass_range(self) -> tuple[int, int]:
        """Get bandpass filter range (low_hz, high_hz)."""
        low = self.get("audio", "bandpass_low", 300)
        high = self.get("audio", "bandpass_high", 3400)
        return (low, high)

    @bandpass_range.setter
    def bandpass_range(self, value: tuple[int, int]) -> None:
        """Set bandpass filter range."""
        low, high = value
        if low >= high:
            raise ValueError("Low frequency must be less than high frequency")
        self.set("audio", "bandpass_low", low)
        self.set("audio", "bandpass_high", high)

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
