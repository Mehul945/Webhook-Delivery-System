"""
HMAC signature validation service.
"""

import hashlib
import hmac
from typing import Optional

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class HMACValidationError(Exception):
    """Raised when HMAC validation fails."""

    pass


def validate_signature(
    payload: bytes,
    signature: Optional[str],
    secret: Optional[str] = None,
) -> bool:
    """
    Validate HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes
        signature: Signature from X-Signature header
        secret: Optional secret key (uses config if not provided)

    Returns:
        True if signature is valid

    Raises:
        HMACValidationError: If signature is missing or invalid
    """
    if not signature:
        logger.warning("hmac_validation_failed: %s", "missing_signature")
        raise HMACValidationError("Missing X-Signature header")

    settings = get_settings()
    secret_key = secret or settings.hmac_secret

    # Calculate expected signature
    expected = hmac.new(
        secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(signature, expected):
        logger.warning("hmac_validation_failed: %s", "signature_mismatch")
        raise HMACValidationError("Invalid signature")

    logger.debug("hmac_validation_success")
    return True


def generate_signature(payload: bytes, secret: Optional[str] = None) -> str:
    """
    Generate HMAC-SHA256 signature for a payload.

    Useful for testing and client implementations.

    Args:
        payload: Request body bytes
        secret: Optional secret key (uses config if not provided)

    Returns:
        Hex-encoded signature
    """
    settings = get_settings()
    secret_key = secret or settings.hmac_secret

    return hmac.new(
        secret_key.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
