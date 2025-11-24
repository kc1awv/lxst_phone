import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from lxst_phone.core.call_state import CallStateMachine
from lxst_phone.core.reticulum_client import ReticulumClient
from lxst_phone.ui.main_window import MainWindow
from lxst_phone.config import Config
from lxst_phone.identity import (
    load_or_create_identity,
    get_identity_storage_path,
    get_identity_info,
)
from lxst_phone.logging_config import setup_logging, get_logger, get_default_log_file

logger = get_logger("app")


def run_app(argv: list[str] | None = None) -> int:
    """
    Entry point for the GUI app.
    Supports a dev flag to simulate an incoming invite after startup.
    """
    argv = sys.argv[1:] if argv is None else argv

    parser = argparse.ArgumentParser(
        description="LXST Phone prototype",
        add_help=True,
    )
    parser.add_argument(
        "--simulate-incoming",
        action="store_true",
        help="Dev helper: simulate an incoming invite after startup.",
    )
    parser.add_argument(
        "--simulate-delay-ms",
        type=int,
        default=800,
        help="Delay before firing simulated invite (ms).",
    )
    parser.add_argument(
        "--simulate-remote-id",
        type=str,
        default=None,
        help="Remote ID to use for simulated invite (defaults to sim-<suffix>).",
    )
    parser.add_argument(
        "--audio-input-device",
        type=int,
        default=None,
        help="Audio input device index (run list_audio_devices.py to see options).",
    )
    parser.add_argument(
        "--audio-output-device",
        type=int,
        default=None,
        help="Audio output device index (run list_audio_devices.py to see options).",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Disable audio capture/playback (useful for testing with multiple instances).",
    )
    parser.add_argument(
        "--identity",
        type=str,
        default=None,
        help="Path to identity file to use (default: ~/.lxst_phone/identity).",
    )
    parser.add_argument(
        "--new-identity",
        action="store_true",
        help="Create a new identity, replacing any existing one.",
    )
    parser.add_argument(
        "--show-identity",
        action="store_true",
        help="Show identity information and exit.",
    )
    parser.add_argument(
        "--no-announce",
        action="store_true",
        help="Disable automatic presence announcements.",
    )
    parser.add_argument(
        "--announce-period",
        type=int,
        default=None,
        help="Period for presence announcements in minutes (default: 5).",
    )
    parser.add_argument(
        "--display-name",
        type=str,
        default=None,
        help="Display name to use in presence announcements.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO).",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Path to log file (default: ~/.lxst_phone/logs/lxst_phone.log if enabled).",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable logging to file.",
    )
    args, qt_args = parser.parse_known_args(argv)

    log_file = None
    if not args.no_log_file:
        if args.log_file:
            log_file = Path(args.log_file)
        else:
            log_file = get_default_log_file()

    setup_logging(
        level=args.log_level,
        log_file=log_file,
        console=True,
    )

    logger.info("LXST Phone starting")
    logger.debug(f"Command line arguments: {argv}")

    identity_path = Path(args.identity) if args.identity else None

    if args.show_identity:
        identity = load_or_create_identity(identity_path=identity_path)
        info = get_identity_info(identity)
        storage_path = identity_path or get_identity_storage_path()
        logger.info(f"Identity file: {storage_path}")
        logger.info(f"Node ID: {info['node_id']}")
        logger.info(f"Public key: {info['public_key'][:64]}...")
        print(f"Identity file: {storage_path}")
        print(f"Node ID: {info['node_id']}")
        print(f"Public key: {info['public_key'][:64]}...")
        return 0

    qt_argv = [sys.argv[0]] + qt_args
    app = QApplication(qt_argv)

    config = Config()

    audio_input = (
        args.audio_input_device
        if args.audio_input_device is not None
        else config.audio_input_device
    )
    audio_output = (
        args.audio_output_device
        if args.audio_output_device is not None
        else config.audio_output_device
    )
    audio_enabled = (not args.no_audio) and config.audio_enabled

    if args.audio_input_device is not None:
        config.audio_input_device = args.audio_input_device
        config.save()
        logger.info(f"Saved audio input device {args.audio_input_device} to config")
    if args.audio_output_device is not None:
        config.audio_output_device = args.audio_output_device
        config.save()
        logger.info(f"Saved audio output device {args.audio_output_device} to config")

    announce_on_start = (
        (not args.no_announce) if args.no_announce else config.announce_on_start
    )
    announce_period_minutes = (
        args.announce_period
        if args.announce_period is not None
        else config.announce_period_minutes
    )
    display_name = (
        args.display_name if args.display_name is not None else config.display_name
    )

    call_state = CallStateMachine()

    rclient = ReticulumClient(
        identity_path=identity_path, force_new_identity=args.new_identity
    )
    rclient.start()

    local_id = rclient.node_id
    logger.info(f"Local node ID: {local_id}")

    window = MainWindow(
        call_state=call_state,
        local_id=local_id,
        reticulum_client=rclient,
        audio_input_device=audio_input,
        audio_output_device=audio_output,
        audio_enabled=audio_enabled,
        config=config,
    )
    window.show()

    def on_message_from_rns(msg):
        logger.debug(f"on_message_from_rns called for type={msg.msg_type}")
        window.incomingCallMessage.emit(msg)

    rclient.on_message = on_message_from_rns

    if announce_on_start:
        name_info = f" as '{display_name}'" if display_name else ""
        logger.info(f"Sending initial presence announcement{name_info}")
        rclient.send_presence_announce(display_name=display_name or None)

    if announce_on_start and announce_period_minutes > 0:
        presence_timer = QTimer()
        presence_timer.timeout.connect(
            lambda: rclient.send_presence_announce(display_name=display_name or None)
        )
        period_ms = announce_period_minutes * 60 * 1000
        presence_timer.start(period_ms)
        logger.info(
            f"Presence announcements enabled (period: {announce_period_minutes} minutes)"
        )
    else:
        logger.info("Automatic presence announcements disabled")

    if args.simulate_incoming:
        delay = max(0, args.simulate_delay_ms)
        logger.debug(f"Scheduling simulated incoming invite in {delay} ms")

        def _fire_simulated_invite():
            window.simulate_incoming_invite(remote_id=args.simulate_remote_id)

        QTimer.singleShot(delay, _fire_simulated_invite)

    return app.exec()
