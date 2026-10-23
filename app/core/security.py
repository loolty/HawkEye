"""
Password hashing utilities (dependency-free).

Uses PBKDF2-HMAC-SHA256 via hashlib, which ships with Python's standard
library. Stored format:

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

This module is intentionally isolated so the upcoming auth module can reuse
it without touching the database layer.
"""

import hashlib
import hmac
import secrets

from app.core.config import settings

ALGORITHM = "pbkdf2_sha256"


def hash_password(plain: str) -> str:
    """Hash a plaintext password with a per-user random salt."""
    if not plain:
        raise ValueError("Password must not be empty.")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt.encode("utf-8"),
        settings.SECURITY_ITERATIONS,
    )
    return f"{ALGORITHM}${settings.SECURITY_ITERATIONS}${salt}${digest.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """Constant-time check of a plaintext password against the stored hash."""
    try:
        algo, iterations, salt, expected_hex = stored.split("$", 3)
    except ValueError:
        return False
    if algo != ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations),
    )
    return hmac.compare_digest(digest.hex(), expected_hex)
