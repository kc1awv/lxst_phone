"""
Identity management for LXST Phone.

Handles loading, creating, and persisting RNS identities.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import RNS


def get_identity_storage_path() -> Path:
    """Get the path where the identity file is stored."""
    config_dir = Path.home() / ".lxst_phone"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "identity"


def load_or_create_identity(
    identity_path: Optional[Path] = None, force_new: bool = False
) -> RNS.Identity:
    """
    Load an existing identity from file, or create a new one if it doesn't exist.

    Args:
        identity_path: Path to identity file. If None, uses default (~/.lxst_phone/identity)
        force_new: If True, create a new identity even if one exists

    Returns:
        RNS.Identity instance
    """
    if identity_path is None:
        identity_path = get_identity_storage_path()

    if force_new:
        RNS.log(f"[Identity] Creating new identity (force_new=True)")
        identity = RNS.Identity()
        save_identity(identity, identity_path)
        RNS.log(f"[Identity] New identity created and saved to {identity_path}")
        RNS.log(f"[Identity] Node ID: {identity.hash.hex()}")
        return identity

    if identity_path.exists():
        try:
            RNS.log(f"[Identity] Loading identity from {identity_path}")
            identity = RNS.Identity.from_file(str(identity_path))

            # Validate that identity loaded correctly
            if (
                identity is None
                or not hasattr(identity, "hash")
                or identity.hash is None
            ):
                raise ValueError("Identity loaded but is invalid (missing hash)")

            RNS.log(f"[Identity] Identity loaded successfully")
            RNS.log(f"[Identity] Node ID: {identity.hash.hex()}")
            return identity
        except Exception as exc:
            RNS.log(f"[Identity] Failed to load identity from {identity_path}: {exc}")
            RNS.log(f"[Identity] Creating new identity to replace corrupted file")
            # Fall through to create new identity
    else:
        RNS.log(f"[Identity] No identity found at {identity_path}")
        RNS.log(f"[Identity] Creating new identity")

    identity = RNS.Identity()
    save_identity(identity, identity_path)
    RNS.log(f"[Identity] New identity created and saved to {identity_path}")
    RNS.log(f"[Identity] Node ID: {identity.hash.hex()}")
    return identity


def save_identity(identity: RNS.Identity, identity_path: Optional[Path] = None) -> None:
    """
    Save an identity to file.

    Args:
        identity: The RNS.Identity to save
        identity_path: Path to save to. If None, uses default (~/.lxst_phone/identity)
    """
    if identity_path is None:
        identity_path = get_identity_storage_path()

    identity_path.parent.mkdir(parents=True, exist_ok=True)

    identity.to_file(str(identity_path))
    RNS.log(f"[Identity] Saved identity to {identity_path}")

    try:
        os.chmod(identity_path, 0o600)
    except Exception as exc:
        RNS.log(
            f"[Identity] Warning: Could not set permissions on {identity_path}: {exc}"
        )


def validate_identity_file(identity_path: Path) -> bool:
    """
    Check if an identity file is valid and can be loaded.

    Args:
        identity_path: Path to identity file to validate

    Returns:
        True if the identity file is valid, False otherwise
    """
    if not identity_path.exists():
        return False

    try:
        identity = RNS.Identity.from_file(str(identity_path))
        return (
            identity is not None
            and hasattr(identity, "hash")
            and identity.hash is not None
        )
    except Exception:
        return False


def get_identity_info(identity: RNS.Identity) -> dict[str, str]:
    """
    Get information about an identity.

    Args:
        identity: The RNS.Identity to get info for

    Returns:
        Dictionary with identity information
    """
    return {
        "node_id": identity.hash.hex(),
        "public_key": (
            identity.get_public_key().hex() if identity.get_public_key() else ""
        ),
        "hash_length": str(len(identity.hash)),
    }
