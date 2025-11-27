"""
LXST Phone application entry point.

Simplified to use LXST Telephone primitive instead of custom media/signaling.
"""

import argparse
import sys
from pathlib import Path

import RNS
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from lxst_phone.core.telephone import TelephoneManager
from lxst_phone.core.lxmf_peer_discovery import LXMFPeerDiscovery
from lxst_phone.core.lxmf_announcer import LXMFAnnouncer
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
    """
    argv = sys.argv[1:] if argv is None else argv

    parser = argparse.ArgumentParser(
        description="LXST Phone - VoIP over Reticulum",
        add_help=True,
    )
    parser.add_argument(
        "--audio-input-device",
        type=int,
        default=None,
        help="Audio input device index.",
    )
    parser.add_argument(
        "--audio-output-device",
        type=int,
        default=None,
        help="Audio output device index.",
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
        help="Path to log file (default: ~/.lxst_phone/logs/lxst_phone.log).",
    )
    parser.add_argument(
        "--no-log-file",
        action="store_true",
        help="Disable logging to file.",
    )
    parser.add_argument(
        "--rns-config",
        type=str,
        default=None,
        help="Path to Reticulum config directory.",
    )
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Path to config directory (default: ~/.lxst_phone). Used for config.json, peers.json, call_history.json, etc.",
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

    config_dir = (
        Path(args.config_dir) if args.config_dir else Path.home() / ".lxst_phone"
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using config directory: {config_dir}")

    if args.identity:
        identity_path = Path(args.identity)
    else:
        identity_path = config_dir / "identity"

    if args.new_identity and identity_path and identity_path.exists():
        logger.warning(f"Deleting existing identity at {identity_path}")
        identity_path.unlink()

    identity = load_or_create_identity(identity_path=identity_path)

    if args.show_identity:
        info = get_identity_info(identity)
        storage_path = identity_path or get_identity_storage_path()
        logger.info(f"Identity file: {storage_path}")
        logger.info(f"Node ID: {info['node_id']}")
        logger.info(f"Public key: {info['public_key'][:64]}...")
        print(f"Identity file: {storage_path}")
        print(f"Node ID: {info['node_id']}")
        print(f"Public key: {info['public_key'][:64]}...")
        return 0

    logger.info("Initializing Reticulum")
    rns_config_path = args.rns_config if args.rns_config else None
    reticulum = RNS.Reticulum(configdir=rns_config_path)

    try:
        interface_count = len(reticulum.get_interface_stats())
        logger.info(f"Reticulum initialized on {interface_count} interface(s)")
    except Exception as e:
        logger.warning(f"Could not get interface stats (RPC unavailable): {e}")
        logger.info("Reticulum initialized (interface count unavailable)")

    config_path = config_dir / "config.json"
    config = Config(config_path=config_path)

    if args.audio_input_device is not None:
        config.audio_input_device = args.audio_input_device
        config.save()
        logger.info(f"Saved audio input device {args.audio_input_device} to config")

    if args.audio_output_device is not None:
        config.audio_output_device = args.audio_output_device
        config.save()
        logger.info(f"Saved audio output device {args.audio_output_device} to config")

    if args.no_announce:
        config.announce_on_start = False

    qt_argv = [sys.argv[0]] + qt_args
    app = QApplication(qt_argv)

    logger.info("Creating TelephoneManager")
    telephone = TelephoneManager(identity, config)

    logger.info("Creating LXMF peer discovery")
    lxmf_discovery = LXMFPeerDiscovery(identity)

    logger.info("Creating LXMF announcer")
    lxmf_announcer = LXMFAnnouncer(identity, config.display_name)

    if config.announce_on_start:
        logger.info("Announcing LXMF presence on startup")
        lxmf_announcer.announce()

    node_id = identity.hash.hex()
    logger.info(f"Local node ID: {node_id}")

    window = MainWindow(
        telephone=telephone,
        lxmf_discovery=lxmf_discovery,
        lxmf_announcer=lxmf_announcer,
        local_id=node_id,
        config=config,
        config_dir=config_dir,
    )
    window.show()

    def cleanup():
        logger.info("Application shutting down")
        telephone.shutdown()

    app.aboutToQuit.connect(cleanup)

    logger.info("Starting Qt event loop")
    return app.exec()
