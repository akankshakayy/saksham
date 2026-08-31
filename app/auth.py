"""API key authentication for Saksham.

Provides a FastAPI dependency that validates the X-API-Key header
against configured keys. Keys are stored as SHA-256 hashes; raw
keys are never logged or exposed through API responses.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.config.settings import get_settings


@dataclass(frozen=True)
class CallerIdentity:
    """Authenticated caller identity."""

    key_id: str
    identity: str


def _hash_key(raw_key: str) -> str:
    """Hash an API key with SHA-256 for safe storage/comparison."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _get_api_keys() -> dict[str, str]:
    """Return mapping of key_hash -> identity for all configured keys."""
    settings = get_settings()
    keys: dict[str, str] = {}
    for entry in settings.api_keys:
        if ":" in entry:
            raw_key, identity = entry.split(":", 1)
        else:
            raw_key, identity = entry, "default"
        keys[_hash_key(raw_key)] = identity
    return keys


def _get_key_identities() -> dict[str, str]:
    """Return mapping of key_hash -> key_id (short label) for logging."""
    settings = get_settings()
    ids: dict[str, str] = {}
    for i, entry in enumerate(settings.api_keys):
        raw_key = entry.split(":")[0] if ":" in entry else entry
        ids[_hash_key(raw_key)] = f"key_{i}"
    return ids


async def require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> CallerIdentity:
    """FastAPI dependency: require a valid API key.

    Returns CallerIdentity on success.
    Raises HTTPException 401 on missing or invalid key.
    """
    api_keys = _get_api_keys()
    key_ids = _get_key_identities()

    if not api_keys:
        raise HTTPException(
            status_code=503,
            detail={
                "error_code": "AUTH_NOT_CONFIGURED",
                "message": "No API keys configured",
            },
        )

    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error_code": "MISSING_API_KEY",
                "message": "X-API-Key header required",
            },
        )

    provided_hash = _hash_key(x_api_key)

    for key_hash, identity in api_keys.items():
        if hmac.compare_digest(provided_hash, key_hash):
            return CallerIdentity(
                key_id=key_ids.get(key_hash, "unknown"),
                identity=identity,
            )

    raise HTTPException(
        status_code=401,
        detail={
            "error_code": "INVALID_API_KEY",
            "message": "Invalid API key",
        },
    )


def validate_uuid(value: str) -> str:
    """Validate that a string is a valid UUID.

    Returns the value if valid.
    Raises HTTPException 400 if not a valid UUID.
    """
    import re

    if not re.match(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        value,
    ):
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "INVALID_APPLICATION_ID",
                "message": f"Invalid application ID format: '{value}'",
            },
        )
    return value.lower()
