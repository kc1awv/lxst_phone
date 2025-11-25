"""
Media layer managing RNS.Link connections and real-time audio streaming.

Handshake flow (after CALL_ACCEPT):
- Initiator creates an RNS.Link to the remote identity and waits for establishment.
- Responder accepts the inbound link and binds callbacks for data/closed events.
- Once the link is active, both sides exchange a control channel for ping/codec info.
- Audio frames are continuously streamed: capture → Opus encode → RNS send.

Audio pipeline:
- Capture: sounddevice → Opus encode → frame → send over RNS.Link
- Playback: RNS receive → unframe → Opus decode → jitter buffer → sounddevice
"""

from __future__ import annotations

import hashlib
import struct
import threading
import time
from collections import deque
from typing import Callable, Optional, Tuple

from lxst_phone.logging_config import get_logger

logger = get_logger("core.media")

try:
    import RNS  # type: ignore
except ImportError:  # pragma: no cover
    RNS = None  # type: ignore

try:
    import sounddevice as sd  # type: ignore
except ImportError:  # pragma: no cover
    sd = None  # type: ignore

try:
    from opuslib import (  # type: ignore
        Encoder as OpusEncoder,
        Decoder as OpusDecoder,
        APPLICATION_AUDIO,
    )
except ImportError:  # pragma: no cover
    OpusEncoder = None  # type: ignore
    OpusDecoder = None  # type: ignore
    APPLICATION_AUDIO = None  # type: ignore

try:
    import pycodec2  # type: ignore
except ImportError:  # pragma: no cover
    pycodec2 = None  # type: ignore

from lxst_phone.core.call_state import CallInfo

PACKET_TYPE_AUDIO = 0x01
PACKET_TYPE_PING = 0x02
PACKET_TYPE_CONTROL = 0x03

DEFAULT_SAMPLE_RATE = 48000
DEFAULT_FRAME_MS = 20
DEFAULT_CHANNELS = 1
DEFAULT_FRAME_SIZE = int(DEFAULT_SAMPLE_RATE * DEFAULT_FRAME_MS / 1000)
DEFAULT_TARGET_JITTER_MS = 60


class MediaManager:
    """
    Singleton manager for media sessions.

    Replaces global state with a proper singleton pattern that supports
    dependency injection and testing.
    """

    _instance: Optional["MediaManager"] = None

    def __init__(self) -> None:
        self.active_call_id: str | None = None
        self.active_session: "MediaSession | None" = None
        self.reticulum_client: object | None = None

    @classmethod
    def get_instance(cls) -> "MediaManager":
        """Get or create the singleton MediaManager instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None

    def start_session(
        self,
        call_info: CallInfo,
        reticulum_client: object,
        audio_input_device: Optional[int] = None,
        audio_output_device: Optional[int] = None,
        audio_enabled: bool = True,
        codec_type: str = "opus",
        opus_bitrate: int = 24000,
        opus_complexity: int = 10,
        codec2_mode: int = 3200,
    ) -> None:
        """Start a new media session for the given call."""
        # Stop any existing session first to prevent race conditions
        if self.active_session:
            logger.warning(
                f"Stopping existing media session (call_id={self.active_call_id}) "
                f"before starting new one (call_id={call_info.call_id})"
            )
            self.stop_session()
        
        self.active_call_id = call_info.call_id
        self.reticulum_client = reticulum_client
        self.active_session = MediaSession(
            call_info,
            reticulum_client,
            audio_input_device=audio_input_device,
            audio_output_device=audio_output_device,
            audio_enabled=audio_enabled,
            codec_type=codec_type,
            opus_bitrate=opus_bitrate,
            opus_complexity=opus_complexity,
            codec2_mode=codec2_mode,
        )
        self.active_session.initiate_link()
        if hasattr(reticulum_client, "on_media_link"):
            reticulum_client.on_media_link = self.handle_incoming_link
        logger.info(
            f"start_media_session called for call_id={call_info.call_id} "
            f"remote={call_info.remote_id} audio_enabled={audio_enabled} codec={codec_type}"
        )

    def stop_session(self) -> None:
        """Stop the active media session."""
        if self.active_call_id:
            logger.info(f"stop_media_session for call_id={self.active_call_id}")
        if self.active_session:
            link = (
                self.active_session.link
                if hasattr(self.active_session, "link")
                else None
            )
            self.active_session.on_link_closed(link)
            if link and hasattr(link, "teardown"):
                try:
                    link.teardown()  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.error(f"Error tearing down link: {exc}")
        self.active_session = None
        self.active_call_id = None
        if self.reticulum_client and hasattr(self.reticulum_client, "on_media_link"):
            self.reticulum_client.on_media_link = None
        self.reticulum_client = None

    def get_metrics(self) -> Optional[CallMetrics]:
        """Get metrics from the active media session."""
        if self.active_session:
            return self.active_session.get_metrics()
        return None

    def get_security_info(self) -> Optional[dict[str, any]]:
        """Get security info from the active media session."""
        if self.active_session:
            return self.active_session.get_security_info()
        return None

    def verify_sas(self) -> None:
        """Mark the current session's SAS as verified."""
        if self.active_session:
            self.active_session.sas_verified = True

    def handle_incoming_link(self, link: object) -> None:
        """Handle incoming media link."""
        if not self.active_session:
            logger.warning("Inbound media link with no active session; closing?")
            try:
                if hasattr(link, "close"):
                    link.close()
            except Exception:
                pass
            return
        self.active_session.on_incoming_link(link)


_media_manager: MediaManager | None = None


def _get_manager() -> MediaManager:
    """Get the global MediaManager instance."""
    global _media_manager
    if _media_manager is None:
        _media_manager = MediaManager.get_instance()
    return _media_manager


def generate_sas(key_material: bytes, length: int = 4) -> str:
    """
    Generate a Short Authentication String from key material.

    Uses SHA-256 hash and converts to decimal digits for verbal verification.

    Args:
        key_material: Raw bytes from link keys or identity
        length: Number of digits (default 4 for easy verification)

    Returns:
        String of decimal digits (e.g., "7342")
    """
    hash_bytes = hashlib.sha256(key_material).digest()
    value = int.from_bytes(hash_bytes[:4], byteorder="big")
    digits = 10**length
    sas_value = value % digits
    return f"{sas_value:0{length}d}"


def secure_zero_bytes(data: bytearray) -> None:
    """
    Securely zero out a bytearray to prevent sensitive data from lingering in memory.

    Note: Python's garbage collector may still leave copies, but this helps.
    """
    if isinstance(data, bytearray):
        for i in range(len(data)):
            data[i] = 0


class FrameFramer:
    """Tiny helper to add/remove a 1-byte type prefix and optional sequence number on link payloads."""

    @staticmethod
    def frame(packet_type: int, payload: bytes, seq: Optional[int] = None) -> bytes:
        if not (0 <= packet_type <= 255):
            raise ValueError("packet_type must fit in one byte")
        result = bytes([packet_type])
        if packet_type == PACKET_TYPE_AUDIO and seq is not None:
            result += struct.pack("!H", seq & 0xFFFF)  # 16-bit sequence number
        return result + payload

    @staticmethod
    def parse(raw: bytes) -> Tuple[int, bytes, Optional[int]]:
        if not raw:
            raise ValueError("empty media packet")
        packet_type = raw[0]
        if packet_type == PACKET_TYPE_AUDIO and len(raw) >= 3:
            seq = struct.unpack("!H", raw[1:3])[0]
            return packet_type, raw[3:], seq
        return packet_type, raw[1:], None


class CallMetrics:
    """
    Tracks audio quality metrics for a call session.
    """

    def __init__(self) -> None:
        self.rtt_samples: deque[float] = deque(maxlen=100)
        self.rtt_min: Optional[float] = None
        self.rtt_max: Optional[float] = None
        self.rtt_avg: Optional[float] = None

        self.packets_sent = 0
        self.packets_received = 0
        self.packets_expected = 0
        self.last_seq_received: Optional[int] = None
        self.packets_lost = 0
        self.loss_percentage = 0.0

        self.bytes_sent = 0
        self.bytes_received = 0
        self.bitrate_samples: deque[int] = deque(maxlen=50)  # frame sizes
        self.avg_bitrate_kbps = 0.0

        self.input_level = 0.0
        self.output_level = 0.0

        self.jitter_ms = 0.0

    def record_rtt(self, rtt_ms: float) -> None:
        """Record a new RTT sample and update stats."""
        self.rtt_samples.append(rtt_ms)
        if self.rtt_min is None or rtt_ms < self.rtt_min:
            self.rtt_min = rtt_ms
        if self.rtt_max is None or rtt_ms > self.rtt_max:
            self.rtt_max = rtt_ms
        if self.rtt_samples:
            self.rtt_avg = sum(self.rtt_samples) / len(self.rtt_samples)

    def record_packet_sent(self, size: int) -> None:
        """Record an outgoing packet."""
        self.packets_sent += 1
        self.bytes_sent += size
        self.bitrate_samples.append(size)
        self._update_bitrate()

    def record_packet_received(self, seq: int, size: int) -> None:
        """Record an incoming packet and detect loss."""
        self.packets_received += 1
        self.bytes_received += size

        if self.last_seq_received is not None:
            expected_seq = (self.last_seq_received + 1) % 65536
            if seq != expected_seq:
                if seq > expected_seq:
                    gap = seq - expected_seq
                else:
                    gap = (65536 - expected_seq) + seq
                self.packets_lost += gap
                self.packets_expected += gap

        self.last_seq_received = seq
        self.packets_expected += 1
        self._update_loss_percentage()

    def _update_loss_percentage(self) -> None:
        """Calculate packet loss percentage."""
        if self.packets_expected > 0:
            self.loss_percentage = (self.packets_lost / self.packets_expected) * 100.0

    def _update_bitrate(self) -> None:
        """Calculate average bitrate from recent frame sizes."""
        if self.bitrate_samples:
            avg_frame_bytes = sum(self.bitrate_samples) / len(self.bitrate_samples)
            bits_per_sec = avg_frame_bytes * 8 * 50
            self.avg_bitrate_kbps = bits_per_sec / 1000.0

    def get_connection_quality(self) -> str:
        """
        Determine connection quality based on metrics.

        Returns:
            "Good", "Fair", or "Poor"
        """
        if self.rtt_avg is None or self.packets_expected < 10:
            return "Unknown"

        rtt_score = 0
        if self.rtt_avg < 200:
            rtt_score = 2  # Good
        elif self.rtt_avg < 500:
            rtt_score = 1  # Fair
        else:
            rtt_score = 0  # Poor

        loss_score = 0
        if self.loss_percentage < 2.0:
            loss_score = 2  # Good
        elif self.loss_percentage < 5.0:
            loss_score = 1  # Fair
        else:
            loss_score = 0  # Poor

        combined_score = (rtt_score + loss_score) / 2.0

        if combined_score >= 1.5:
            return "Good"
        elif combined_score >= 0.5:
            return "Fair"
        else:
            return "Poor"


class JitterBuffer:
    """
    Optimized jitter buffer with target delay and adaptive sizing.
    Uses deque with maxlen for O(1) operations and automatic overflow handling.
    """

    def __init__(self, max_frames: int = 50) -> None:
        self.max_frames = max_frames
        self._frames: deque[Tuple[float, bytes]] = deque(maxlen=max_frames)

    def push(self, frame: bytes) -> None:
        """Add frame to buffer. Oldest frame automatically dropped if full."""
        now = time.time()
        self._frames.append((now, frame))  # maxlen handles overflow automatically

    def pop_ready(self, target_delay_ms: int) -> Optional[bytes]:
        """Pop frame if enough time has elapsed since it was queued."""
        if not self._frames:
            return None
        ts, frame = self._frames[0]
        now = time.time()
        delay_ms = (now - ts) * 1000
        if delay_ms < target_delay_ms:
            return None
        self._frames.popleft()
        return frame

    def get_depth(self) -> int:
        """Get current buffer depth."""
        return len(self._frames)

    def clear(self) -> None:
        """Clear all buffered frames."""
        self._frames.clear()


class AudioPipeline:
    """
    Real-time audio pipeline for VoIP calls.

    Supports Opus and Codec2 codecs with configurable bitrates.
    """

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        frame_ms: int = DEFAULT_FRAME_MS,
        channels: int = DEFAULT_CHANNELS,
        target_jitter_ms: int = DEFAULT_TARGET_JITTER_MS,
        input_device: Optional[int] = None,
        output_device: Optional[int] = None,
        codec_type: str = "opus",
        opus_bitrate: int = 24000,
        opus_complexity: int = 10,
        codec2_mode: int = 3200,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.channels = channels
        self.frame_size = int(sample_rate * frame_ms / 1000)
        self.target_jitter_ms = target_jitter_ms
        self.input_device = input_device
        self.output_device = output_device
        self.codec_type = codec_type.lower()
        self.opus_bitrate = opus_bitrate
        self.opus_complexity = opus_complexity
        self.codec2_mode = codec2_mode
        self.running = False
        self._send_callback: Optional[Callable[[bytes], None]] = None
        self._level_callback: Optional[Callable[[float, float], None]] = (
            None  # (input, output)
        )
        self._capture_thread: Optional[threading.Thread] = None
        self._play_thread: Optional[threading.Thread] = None
        self._play_queue = JitterBuffer(max_frames=200)
        self._stream_in = None
        self._stream_out = None
        self._encoder = None
        self._decoder = None
        self.input_level = 0.0  # Current input level (0.0-1.0)
        self.output_level = 0.0  # Current output level (0.0-1.0)

        self._have_audio = bool(sd)
        if self.codec_type == "opus":
            self._init_opus()
        elif self.codec_type == "codec2":
            self._init_codec2()
        else:
            logger.error(f"Unknown codec type: {codec_type}")
            self._have_audio = False

    def _init_opus(self) -> None:
        """Initialize Opus codec."""
        if not OpusEncoder or not OpusDecoder or not APPLICATION_AUDIO:
            logger.warning("Opus codec not available (install opuslib)")
            self._have_audio = False
            return
        try:
            self._encoder = OpusEncoder(  # type: ignore[call-arg]
                self.sample_rate, self.channels, APPLICATION_AUDIO
            )
            if hasattr(self._encoder, "bitrate"):
                self._encoder.bitrate = self.opus_bitrate  # type: ignore
            if hasattr(self._encoder, "complexity"):
                self._encoder.complexity = self.opus_complexity  # type: ignore

            self._decoder = OpusDecoder(  # type: ignore[call-arg]
                self.sample_rate, self.channels
            )
            logger.info(
                f"Opus codec initialized (bitrate={self.opus_bitrate}, complexity={self.opus_complexity})"
            )
        except Exception as exc:  # pragma: no cover - depends on local install
            logger.error(f"Failed to init Opus codec: {exc}")
            self._have_audio = False

    def _init_codec2(self) -> None:
        """Initialize Codec2 codec."""
        if not pycodec2:
            logger.warning("Codec2 not available (install pycodec2)")
            self._have_audio = False
            return
        try:
            codec2_sample_rate = 8000

            self._encoder = pycodec2.Codec2(self.codec2_mode)  # type: ignore
            self._decoder = pycodec2.Codec2(self.codec2_mode)  # type: ignore

            self.sample_rate = codec2_sample_rate
            self.frame_size = int(codec2_sample_rate * self.frame_ms / 1000)

            logger.info(
                f"Codec2 initialized (mode={self.codec2_mode} bps, sr={codec2_sample_rate})"
            )
        except Exception as exc:
            logger.error(f"Failed to init Codec2: {exc}")
            self._have_audio = False

    def set_level_callback(self, callback: Callable[[float, float], None]) -> None:
        """Set callback for audio level updates (input_level, output_level)."""
        self._level_callback = callback

    def start(self, send_callback: Callable[[bytes], None]) -> None:
        self._send_callback = send_callback
        if not self._have_audio:
            logger.warning(
                f"AudioPipeline running in stub mode ({self.codec_type} codec or sounddevice missing)"
            )
            return

        if self.running:
            return
        self.running = True

        try:
            self._stream_in = sd.RawInputStream(  # type: ignore[assignment]
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.frame_size,
                device=self.input_device,
            )
            self._stream_out = sd.RawOutputStream(  # type: ignore[assignment]
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.frame_size,
                device=self.output_device,
            )
        except Exception as exc:
            logger.error(
                f"Failed to open audio devices (in={self.input_device}, out={self.output_device}): {exc}"
            )
            logger.error("Run 'python -m sounddevice' to list available devices")
            self.running = False
            return
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="AudioCapture", daemon=True
        )
        self._play_thread = threading.Thread(
            target=self._play_loop, name="AudioPlay", daemon=True
        )
        self._stream_in.start()
        self._stream_out.start()
        self._capture_thread.start()
        self._play_thread.start()
        logger.info(
            f"AudioPipeline start (codec={self.codec_type}, sr={self.sample_rate}, "
            f"frame_ms={self.frame_ms}, channels={self.channels})"
        )
        logger.info(
            f"using audio devices in={self.input_device}, out={self.output_device})"
        )

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False

        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=1.0)
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1.0)

        if self._stream_in:
            try:
                self._stream_in.stop()
                self._stream_in.close()
            except Exception as exc:
                logger.error(f"Error closing input stream: {exc}")
            finally:
                self._stream_in = None
        if self._stream_out:
            try:
                self._stream_out.stop()
                self._stream_out.close()
            except Exception as exc:
                logger.error(f"Error closing output stream: {exc}")
            finally:
                self._stream_out = None
        logger.info("AudioPipeline stop")

    @staticmethod
    def _calculate_rms_level(pcm_data: bytes) -> float:
        """Calculate RMS level from int16 PCM data, return 0.0-1.0."""
        import array

        samples = array.array("h", pcm_data)  # int16
        if not samples:
            return 0.0
        sum_squares = sum(s * s for s in samples)
        rms = (sum_squares / len(samples)) ** 0.5
        return min(1.0, rms / 32768.0)

    def handle_incoming_frame(self, encoded: bytes) -> None:
        if not self._have_audio or not self._decoder:
            logger.debug(f"(stub) drop incoming audio frame len={len(encoded)}")
            return
        try:
            if self.codec_type == "opus":
                pcm = self._decoder.decode(encoded, self.frame_size)  # type: ignore[arg-type]
            else:  # codec2
                pcm = self._decoder.decode(encoded)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.error(f"decode failed: {exc}")
            return
        self._play_queue.push(pcm)

    def _capture_loop(self) -> None:
        assert self._encoder is not None
        assert self._stream_in is not None
        frame_bytes = self.frame_size * self.channels * 2  # int16 bytes
        logger.debug("capture loop start")
        while self.running:
            if not self._stream_in:
                break
            try:
                if not self.running:
                    break
                data, _ = self._stream_in.read(self.frame_size)
            except Exception as exc:
                if self.running:  # Only log if we didn't stop intentionally
                    logger.error(f"capture read failed: {exc}")
                break
            if not data or len(data) < frame_bytes:
                continue
            try:
                data_bytes = bytes(data)

                self.input_level = self._calculate_rms_level(data_bytes)
                if self._level_callback:
                    self._level_callback(self.input_level, self.output_level)

                if self.codec_type == "opus":
                    encoded = self._encoder.encode(data_bytes, self.frame_size)  # type: ignore[arg-type]
                else:  # codec2
                    encoded = self._encoder.encode(data_bytes)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.error(f"encode failed: {exc}")
                continue
            if self._send_callback:
                self._send_callback(encoded)
        logger.debug("capture loop exit")

    def _play_loop(self) -> None:
        assert self._stream_out is not None
        logger.debug("playback loop start")
        frames_played = 0
        wait_cycles = 0
        while self.running:
            if not self._stream_out:
                break
            frame = self._play_queue.pop_ready(self.target_jitter_ms)
            if frame is None:
                wait_cycles += 1
                time.sleep(self.frame_ms / 2000)  # half frame wait
                continue
            try:
                if not self.running or not self._stream_out:
                    break
                if not isinstance(frame, bytes):
                    frame = bytes(frame)

                self.output_level = self._calculate_rms_level(frame)
                if self._level_callback:
                    self._level_callback(self.input_level, self.output_level)

                self._stream_out.write(frame)
                frames_played += 1
            except Exception as exc:
                if self.running:  # Only log if we didn't stop intentionally
                    logger.error(f"playback failed: {exc}")
                break
        logger.debug(
            f"playback loop exit (played {frames_played} frames, waited {wait_cycles} cycles)"
        )


class MediaSession:
    """
    RNS-backed media session managing a single call's audio and link state.

    Owns the RNS.Link instance and coordinates the audio pipeline.
    """

    def __init__(
        self,
        call_info: CallInfo,
        reticulum_client: object,
        audio_input_device: Optional[int] = None,
        audio_output_device: Optional[int] = None,
        audio_enabled: bool = True,
        codec_type: str = "opus",
        opus_bitrate: int = 24000,
        opus_complexity: int = 10,
        codec2_mode: int = 3200,
    ) -> None:
        self.call_info = call_info
        self.reticulum_client = reticulum_client
        self.link: Optional[object] = None  # will be an RNS.Link
        self.active = False
        self.initiated_by_local = call_info.initiated_by_local
        self.remote_media_dest = call_info.remote_media_dest
        self.remote_identity_key = call_info.remote_identity_key
        self.local_media_dest: Optional[str] = getattr(
            reticulum_client, "media_dest_hash", None
        )
        self.jitter = JitterBuffer()
        self.audio_enabled = audio_enabled
        self.metrics = CallMetrics()  # Track call quality metrics
        self._tx_seq = 0  # Outgoing sequence number

        # Security tracking
        self.is_encrypted = False
        self.sas_code: Optional[str] = None
        self.sas_verified = False
        self.link_timeout: Optional[threading.Timer] = None

        if audio_enabled:
            self.audio = AudioPipeline(
                input_device=audio_input_device,
                output_device=audio_output_device,
                codec_type=codec_type,
                opus_bitrate=opus_bitrate,
                opus_complexity=opus_complexity,
                codec2_mode=codec2_mode,
            )
        else:
            self.audio = AudioPipeline(
                input_device=audio_input_device,
                output_device=audio_output_device,
                codec_type=codec_type,
                opus_bitrate=opus_bitrate,
                opus_complexity=opus_complexity,
                codec2_mode=codec2_mode,
            )
            self.audio._have_audio = False
        self._last_ping_ts: Optional[float] = None
        self._audio_sending_started = False

    def _on_link_timeout(self) -> None:
        """Handle link establishment timeout."""
        # Clear the timeout reference
        self.link_timeout = None
        
        if not self.active and self.link:
            logger.warning(
                f"Link establishment timeout for call_id={self.call_info.call_id}"
            )
            try:
                if hasattr(self.link, "teardown"):
                    self.link.teardown()
            except Exception as exc:
                logger.error(f"Error tearing down timed-out link: {exc}")
            self.link = None
        elif self.active:
            logger.debug(f"Link timeout fired but link already active for call_id={self.call_info.call_id}")

    def _start_link_monitor(self) -> None:
        """Monitor link status periodically during establishment."""
        def check_status():
            if self.link and not self.active:
                status = getattr(self.link, 'status', 'unknown')
                logger.debug(f"Link status check: {status} (call_id={self.call_info.call_id})")
                # Schedule next check in 2 seconds if still not active
                if not self.active and self.link:
                    timer = threading.Timer(2.0, check_status)
                    timer.daemon = True
                    timer.start()
        
        # Start first check in 2 seconds
        timer = threading.Timer(2.0, check_status)
        timer.daemon = True
        timer.start()

    def initiate_link(self) -> None:
        """
        Initiate or prepare to accept an RNS.Link based on call role.
        """
        if self.initiated_by_local:
            self._start_initiator_handshake()
        else:
            self._start_responder_handshake()

    def _start_initiator_handshake(self) -> None:
        """
        Create an outbound RNS.Link to the callee's media destination.
        """
        if not self.remote_media_dest:
            logger.error("Cannot initiate link: remote media dest missing")
            return
        if not self.remote_identity_key:
            logger.error(
                f"Cannot initiate link: remote identity key missing for {self.remote_id[:16]}... "
                f"Peer may not have announced their presence yet."
            )
            return
        
        logger.debug(
            f"Initiator handshake: remote_media_dest={self.remote_media_dest}, "
            f"remote_identity_key={self.remote_identity_key[:32] if self.remote_identity_key else 'None'}..."
        )
        
        try:
            link = self.reticulum_client.create_media_link(
                remote_media_dest=self.remote_media_dest,
                remote_identity_key_b64=self.remote_identity_key,
                on_established=self.on_link_established,
                on_closed=self.on_link_closed,
            )
            logger.info(
                f"(initiator) outbound link attempt to {self.remote_media_dest}"
            )
            self.link = link

            # Monitor link status
            logger.debug(f"Link created, initial status: {getattr(link, 'status', 'unknown')}")
            
            # Start a periodic status monitor
            self._start_link_monitor()
            
            self.link_timeout = threading.Timer(30.0, self._on_link_timeout)
            self.link_timeout.daemon = True
            self.link_timeout.start()
        except (ValueError, TypeError) as exc:
            logger.error(f"Invalid parameters for link creation: {exc}")
            self.link = None
        except Exception as exc:
            logger.error(f"Failed to start initiator link: {exc}")
            self.link = None

    def _start_responder_handshake(self) -> None:
        """
        Wait for inbound RNS.Link requests and bind callbacks via ReticulumClient.
        """
        logger.info("(responder) awaiting inbound RNS.Link for this call")

    def on_incoming_link(self, link: object) -> None:
        """
        Called when the ReticulumClient reports an inbound media link.
        """
        if self.initiated_by_local:
            logger.warning("Unexpected inbound link while we are initiator; ignoring")
            return
        self.on_link_established(link)

    def on_link_established(self, link: object) -> None:
        """Called when the RNS.Link is active (either initiator or responder)."""
        if self.link_timeout:
            self.link_timeout.cancel()
            self.link_timeout = None

        self.link = link
        self.active = True
        self._bind_link_callbacks(link)

        if hasattr(link, "encryption_enabled"):
            self.is_encrypted = bool(link.encryption_enabled)  # type: ignore[attr-defined]
        elif hasattr(link, "encrypted"):
            self.is_encrypted = bool(link.encrypted)  # type: ignore[attr-defined]
        else:
            self.is_encrypted = True

        # Generate SAS for verification
        if hasattr(link, "hash"):
            link_hash = link.hash  # type: ignore[attr-defined]
            self.sas_code = generate_sas(link_hash)
        elif hasattr(link, "link_id"):
            link_id = link.link_id  # type: ignore[attr-defined]
            if isinstance(link_id, bytes):
                self.sas_code = generate_sas(link_id)

        encryption_status = "encrypted" if self.is_encrypted else "UNENCRYPTED"
        sas_info = f", SAS: {self.sas_code}" if self.sas_code else ""
        logger.info(
            f"Link established for call_id={self.call_info.call_id} ({encryption_status}{sas_info})"
        )

        self.audio.set_level_callback(self._on_audio_levels)

        self.audio.start(self.send_audio_frame)
        self._send_ping(initial=True)

    def _on_audio_levels(self, input_level: float, output_level: float) -> None:
        """Update metrics with current audio levels."""
        self.metrics.input_level = input_level
        self.metrics.output_level = output_level

    def on_link_closed(self, link: object) -> None:
        # Cancel link timeout timer if still running
        if self.link_timeout:
            self.link_timeout.cancel()
            self.link_timeout = None
        
        link_status = getattr(link, "status", "unknown") if link else "None"
        logger.info(
            f"Link closed for call_id={self.call_info.call_id} "
            f"(was_active={self.active}, link_status={link_status})"
        )
        
        self.active = False
        self.audio.stop()

    def send_audio_frame(self, frame: bytes) -> None:
        if not self.active or not self.link:
            return

        link_status = getattr(self.link, "status", None)
        if link_status is not None and link_status != 2:  # Not ACTIVE
            return

        if not self._audio_sending_started:
            self._audio_sending_started = True
            logger.info(
                f"Started sending audio frames for call_id={self.call_info.call_id}"
            )

        payload = FrameFramer.frame(PACKET_TYPE_AUDIO, frame, seq=self._tx_seq)
        self._tx_seq = (self._tx_seq + 1) % 65536  # 16-bit wraparound

        self.metrics.record_packet_sent(len(payload))

        try:
            packet = RNS.Packet(self.link, payload)  # type: ignore[arg-type]
            packet.send()
        except Exception as exc:
            logger.error(f"Failed to send audio packet (status={link_status}): {exc}")

    def handle_audio_frame(self, frame: bytes) -> None:
        self.audio.handle_incoming_frame(frame)

    def on_link_data(self, data: bytes) -> None:
        """
        Callback for raw data received on the media link.
        """
        try:
            packet_type, payload, seq = FrameFramer.parse(data)
        except Exception as exc:
            logger.error(f"Failed to parse media packet: {exc}")
            return

        if packet_type == PACKET_TYPE_AUDIO:
            if seq is not None:
                self.metrics.record_packet_received(seq, len(data))
            self.handle_audio_frame(payload)
            return
        if packet_type == PACKET_TYPE_PING:
            self._handle_ping(payload)
            return
        if packet_type == PACKET_TYPE_CONTROL:
            self._handle_control(payload)
            return

        logger.warning(f"Unknown media packet type: {packet_type}")

    def _handle_ping(self, payload: bytes) -> None:
        """
        Payload: [direction (0=req,1=resp)] + 8-byte double timestamp (seconds).
        """
        if len(payload) < 9:
            logger.warning("Ping payload too short")
            return
        direction = payload[0]
        ts = struct.unpack("!d", payload[1:9])[0]
        if direction == 0:
            resp = bytes([1]) + payload[1:9]
            self._send_control_packet(PACKET_TYPE_PING, resp)
            return
        if direction == 1:
            rtt_ms = (time.time() - ts) * 1000
            self.metrics.record_rtt(rtt_ms)  # Track RTT metrics
            logger.debug(f"Ping RTT ~{rtt_ms:.1f} ms (avg: {self.metrics.rtt_avg:.1f})")

    def _handle_control(self, payload: bytes) -> None:
        logger.debug(f"Received CONTROL payload ({len(payload)} bytes)")

    def _send_ping(self, initial: bool = False) -> None:
        ts = struct.pack("!d", time.time())
        direction = bytes([0])
        payload = direction + ts
        self._send_control_packet(PACKET_TYPE_PING, payload)
        if initial:
            self._last_ping_ts = time.time()

    def _send_control_packet(self, packet_type: int, payload: bytes) -> None:
        if not self.active:
            return
        framed = FrameFramer.frame(packet_type, payload)
        if self.link:
            try:
                packet = RNS.Packet(self.link, framed)  # type: ignore[arg-type]
                packet.send()
            except Exception as exc:
                logger.error(f"Failed to send control packet: {exc}")

    def get_metrics(self) -> CallMetrics:
        """Get current call metrics for UI display."""
        self.metrics.jitter_ms = self.jitter.get_depth() * DEFAULT_FRAME_MS
        return self.metrics

    def get_security_info(self) -> dict[str, any]:
        """Get security information for UI display."""
        return {
            "encrypted": self.is_encrypted,
            "sas_code": self.sas_code,
            "sas_verified": self.sas_verified,
        }

    def on_link_packet(self, message: bytes, packet: object) -> None:
        """
        Packet-level callback called by RNS with (message, packet).
        message: the raw data
        packet: the RNS.Packet object
        """
        if message:
            self.on_link_data(message)

    def _bind_link_callbacks(self, link: object) -> None:
        """
        Attach data/packet/closed callbacks using whatever API the link exposes.
        """
        if hasattr(link, "set_data_callback"):
            link.set_data_callback(self.on_link_data)  # type: ignore[attr-defined]
        elif hasattr(link, "data_callback"):
            link.data_callback = self.on_link_data  # type: ignore[attr-defined]

        if hasattr(link, "set_packet_callback"):
            link.set_packet_callback(self.on_link_packet)  # type: ignore[attr-defined]
        elif hasattr(link, "packet_callback"):
            link.packet_callback = self.on_link_packet  # type: ignore[attr-defined]

        if hasattr(link, "set_link_closed_callback"):
            link.set_link_closed_callback(self.on_link_closed)  # type: ignore[attr-defined]
        elif hasattr(link, "link_closed_callback"):
            link.link_closed_callback = self.on_link_closed  # type: ignore[attr-defined]


def start_media_session(
    call_info: CallInfo,
    reticulum_client: object,
    audio_input_device: Optional[int] = None,
    audio_output_device: Optional[int] = None,
    audio_enabled: bool = True,
    codec_type: str = "opus",
    opus_bitrate: int = 24000,
    opus_complexity: int = 10,
    codec2_mode: int = 3200,
) -> None:
    """Start a media session (legacy API using MediaManager)."""
    manager = _get_manager()
    manager.start_session(
        call_info,
        reticulum_client,
        audio_input_device=audio_input_device,
        audio_output_device=audio_output_device,
        audio_enabled=audio_enabled,
        codec_type=codec_type,
        opus_bitrate=opus_bitrate,
        opus_complexity=opus_complexity,
        codec2_mode=codec2_mode,
    )


def stop_media_session() -> None:
    """Stop the active media session (legacy API using MediaManager)."""
    manager = _get_manager()
    manager.stop_session()


def get_current_metrics() -> Optional[CallMetrics]:
    """Get metrics from the active media session (legacy API)."""
    manager = _get_manager()
    return manager.get_metrics()


def get_security_info() -> Optional[dict[str, any]]:
    """Get security info from the active media session (legacy API)."""
    manager = _get_manager()
    return manager.get_security_info()


def verify_sas() -> None:
    """Mark the current session's SAS as verified (legacy API)."""
    manager = _get_manager()
    manager.verify_sas()


def handle_incoming_link(link: object) -> None:
    """Handle incoming media link (legacy API)."""
    manager = _get_manager()
    manager.handle_incoming_link(link)
