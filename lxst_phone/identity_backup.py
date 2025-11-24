"""
Identity backup and export functionality for LXST Phone.

Allows users to export their identity for backup and import for restoration.
Exports are encrypted with a user-provided password.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

try:
    import RNS
except ImportError:
    RNS = None  # type: ignore

from lxst_phone.logging_config import get_logger

logger = get_logger("identity_backup")


def export_identity(
    identity: "RNS.Identity",  # type: ignore
    export_path: Path,
    password: str,
) -> None:
    """
    Export identity to an encrypted backup file.

    Args:
        identity: The RNS.Identity to export
        export_path: Path where to save the encrypted backup
        password: Password to encrypt the backup

    Raises:
        ValueError: If password is too short or identity is invalid
        OSError: If file cannot be written
    """
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    if not identity or not hasattr(identity, "get_private_key"):
        raise ValueError("Invalid identity")

    try:
        private_key = identity.get_private_key()
        if not private_key:
            raise ValueError("Cannot export identity: no private key available")

        backup_data = {
            "version": 1,
            "node_id": identity.hash.hex(),
            "private_key": base64.b64encode(private_key).decode("ascii"),
        }

        json_data = json.dumps(backup_data, indent=2)

        password_identity = RNS.Identity.from_bytes(password.encode("utf-8"))

        encrypted_data = password_identity.encrypt(json_data.encode("utf-8"))

        export_package = {
            "format": "lxst_phone_identity_backup",
            "version": 1,
            "encrypted_data": base64.b64encode(encrypted_data).decode("ascii"),
            "password_hash": password_identity.hash.hex()[
                :16
            ],  # First 16 chars for verification
        }

        export_path.parent.mkdir(parents=True, exist_ok=True)
        with open(export_path, "w") as f:
            json.dump(export_package, f, indent=2)

        os.chmod(export_path, 0o600)

        logger.info(f"Identity exported to {export_path}")
        logger.info(f"Node ID: {identity.hash.hex()}")

    except Exception as exc:
        logger.error(f"Failed to export identity: {exc}")
        raise


def import_identity(
    import_path: Path,
    password: str,
) -> "RNS.Identity":  # type: ignore
    """
    Import identity from an encrypted backup file.

    Args:
        import_path: Path to the encrypted backup file
        password: Password to decrypt the backup

    Returns:
        The restored RNS.Identity

    Raises:
        ValueError: If password is incorrect or file is invalid
        OSError: If file cannot be read
    """
    if not password:
        raise ValueError("Password required")

    if not import_path.exists():
        raise OSError(f"Backup file not found: {import_path}")

    try:
        with open(import_path, "r") as f:
            export_package = json.load(f)

        if export_package.get("format") != "lxst_phone_identity_backup":
            raise ValueError("Invalid backup file format")

        if export_package.get("version") != 1:
            raise ValueError(
                f"Unsupported backup version: {export_package.get('version')}"
            )

        password_identity = RNS.Identity.from_bytes(password.encode("utf-8"))

        expected_hash = export_package.get("password_hash", "")
        actual_hash = password_identity.hash.hex()[:16]
        if expected_hash != actual_hash:
            raise ValueError("Incorrect password")

        encrypted_data = base64.b64decode(export_package["encrypted_data"])
        decrypted_data = password_identity.decrypt(encrypted_data)

        backup_data = json.loads(decrypted_data.decode("utf-8"))

        if backup_data.get("version") != 1:
            raise ValueError(
                f"Unsupported backup data version: {backup_data.get('version')}"
            )

        private_key = base64.b64decode(backup_data["private_key"])
        identity = RNS.Identity.from_bytes(private_key)

        restored_node_id = identity.hash.hex()
        expected_node_id = backup_data["node_id"]
        if restored_node_id != expected_node_id:
            logger.warning(
                f"Restored node ID {restored_node_id} doesn't match "
                f"expected {expected_node_id}"
            )

        logger.info(f"Identity imported from {import_path}")
        logger.info(f"Node ID: {identity.hash.hex()}")

        return identity

    except json.JSONDecodeError as exc:
        logger.error(f"Invalid backup file format: {exc}")
        raise ValueError("Corrupted or invalid backup file") from exc
    except KeyError as exc:
        logger.error(f"Missing required field in backup: {exc}")
        raise ValueError("Incomplete backup file") from exc
    except Exception as exc:
        logger.error(f"Failed to import identity: {exc}")
        raise


def validate_backup_file(import_path: Path) -> dict[str, str]:
    """
    Validate a backup file without decrypting it.

    Args:
        import_path: Path to the backup file

    Returns:
        Dictionary with backup metadata (format, version)

    Raises:
        ValueError: If file is invalid
        OSError: If file cannot be read
    """
    if not import_path.exists():
        raise OSError(f"Backup file not found: {import_path}")

    try:
        with open(import_path, "r") as f:
            export_package = json.load(f)

        format_type = export_package.get("format", "unknown")
        version = export_package.get("version", "unknown")

        return {
            "format": format_type,
            "version": str(version),
            "valid": format_type == "lxst_phone_identity_backup",
        }

    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON file") from exc
    except Exception as exc:
        raise ValueError(f"Cannot read backup file: {exc}") from exc
