"""
Ringtone management for LXST Phone.

Handles ringtone playback for incoming and outgoing calls,
with auto-copy of default ringtones on first startup.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

try:
    import pyaudio
    import wave
    import threading
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

from lxst_phone.logging_config import get_logger

logger = get_logger("ringtone")


class RingtonePlayer:
    """
    Plays ringtone audio files for incoming and outgoing calls.
    Supports looping playback until stopped.
    """

    def __init__(
        self,
        incoming_ringtone_path: Optional[Path] = None,
        outgoing_ringtone_path: Optional[Path] = None,
        enabled: bool = True,
    ) -> None:
        """
        Initialize ringtone player.

        Args:
            incoming_ringtone_path: Path to incoming call ringtone WAV file
            outgoing_ringtone_path: Path to outgoing call ringtone WAV file
            enabled: Whether ringtones are enabled
        """
        self.incoming_ringtone_path = incoming_ringtone_path
        self.outgoing_ringtone_path = outgoing_ringtone_path
        self.enabled = enabled and AUDIO_AVAILABLE

        self._playback_thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._pa: Optional[pyaudio.PyAudio] = None

        if not AUDIO_AVAILABLE:
            logger.warning("PyAudio not available - ringtones disabled")

    def play_incoming(self) -> None:
        """Start playing incoming call ringtone (loops until stopped)."""
        if not self.enabled or not self.incoming_ringtone_path:
            return

        if not self.incoming_ringtone_path.exists():
            logger.warning(f"Incoming ringtone not found: {self.incoming_ringtone_path}")
            return

        self.stop()
        self._stop_flag.clear()
        self._playback_thread = threading.Thread(
            target=self._play_loop,
            args=(self.incoming_ringtone_path,),
            daemon=True,
        )
        self._playback_thread.start()
        logger.debug(f"Started incoming ringtone: {self.incoming_ringtone_path.name}")

    def play_outgoing(self) -> None:
        """Start playing outgoing call ringtone (loops until stopped)."""
        if not self.enabled or not self.outgoing_ringtone_path:
            return

        if not self.outgoing_ringtone_path.exists():
            logger.warning(f"Outgoing ringtone not found: {self.outgoing_ringtone_path}")
            return

        self.stop()
        self._stop_flag.clear()
        self._playback_thread = threading.Thread(
            target=self._play_loop,
            args=(self.outgoing_ringtone_path,),
            daemon=True,
        )
        self._playback_thread.start()
        logger.debug(f"Started outgoing ringtone: {self.outgoing_ringtone_path.name}")

    def stop(self) -> None:
        """Stop playing ringtone."""
        self._stop_flag.set()
        if self._playback_thread and self._playback_thread.is_alive():
            self._playback_thread.join(timeout=1.0)
        self._playback_thread = None
        logger.debug("Stopped ringtone playback")

    def _play_loop(self, wav_path: Path) -> None:
        """
        Play WAV file in a loop until stop flag is set.

        Args:
            wav_path: Path to WAV file to play
        """
        if not AUDIO_AVAILABLE:
            return

        try:
            self._pa = pyaudio.PyAudio()

            while not self._stop_flag.is_set():
                try:
                    with wave.open(str(wav_path), "rb") as wf:
                        stream = self._pa.open(
                            format=self._pa.get_format_from_width(wf.getsampwidth()),
                            channels=wf.getnchannels(),
                            rate=wf.getframerate(),
                            output=True,
                        )

                        chunk_size = 1024
                        data = wf.readframes(chunk_size)

                        while data and not self._stop_flag.is_set():
                            stream.write(data)
                            data = wf.readframes(chunk_size)

                        stream.stop_stream()
                        stream.close()

                except Exception as exc:
                    logger.error(f"Error playing ringtone {wav_path}: {exc}")
                    break

                if not self._stop_flag.wait(0.5):
                    continue
                else:
                    break

        finally:
            if self._pa:
                self._pa.terminate()
                self._pa = None

    def cleanup(self) -> None:
        """Clean up resources."""
        self.stop()


def get_ringtone_dir() -> Path:
    """Get the user's ringtone directory (~/.lxst_phone/ringtones)."""
    ringtone_dir = Path.home() / ".lxst_phone" / "ringtones"
    ringtone_dir.mkdir(parents=True, exist_ok=True)
    return ringtone_dir


def get_default_ringtone_dir() -> Path:
    """Get the package's default ringtone directory."""
    package_dir = Path(__file__).parent
    return package_dir / "resources" / "ringtones"


def copy_default_ringtones() -> None:
    """
    Copy default ringtones from package to user directory on first startup.
    Only copies if user directory doesn't have the default files.
    """
    user_ringtone_dir = get_ringtone_dir()
    default_ringtone_dir = get_default_ringtone_dir()

    if not default_ringtone_dir.exists():
        logger.info(f"No default ringtones found at {default_ringtone_dir}")
        return

    default_files = ["incoming.wav", "outgoing.wav"]

    for filename in default_files:
        src = default_ringtone_dir / filename
        dst = user_ringtone_dir / filename

        if src.exists() and not dst.exists():
            try:
                shutil.copy2(src, dst)
                logger.info(f"Copied default ringtone: {filename}")
            except Exception as exc:
                logger.error(f"Failed to copy {filename}: {exc}")
        elif dst.exists():
            logger.debug(f"User ringtone already exists: {filename}")


def get_ringtone_paths(
    incoming_file: Optional[str] = None,
    outgoing_file: Optional[str] = None,
) -> tuple[Optional[Path], Optional[Path]]:
    """
    Get full paths to ringtone files.

    Args:
        incoming_file: Filename of incoming ringtone (relative to ringtone dir)
        outgoing_file: Filename of outgoing ringtone (relative to ringtone dir)

    Returns:
        Tuple of (incoming_path, outgoing_path). Returns None for missing files.
    """
    ringtone_dir = get_ringtone_dir()

    incoming_path = None
    outgoing_path = None

    if incoming_file:
        path = ringtone_dir / incoming_file
        if path.exists():
            incoming_path = path
        else:
            logger.warning(f"Incoming ringtone not found: {path}")

    if outgoing_file:
        path = ringtone_dir / outgoing_file
        if path.exists():
            outgoing_path = path
        else:
            logger.warning(f"Outgoing ringtone not found: {path}")

    return incoming_path, outgoing_path
