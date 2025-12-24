"""
Tests for HMAC signature validation.
"""

import pytest
from app.services.hmac_validator import (
    validate_signature,
    generate_signature,
    HMACValidationError,
)


class TestHMACValidation:
    """Test HMAC signature validation."""

    def test_generate_signature(self):
        """Test signature generation."""
        payload = b'{"event": "test", "data": "hello"}'
        secret = "test-secret-key"

        signature = generate_signature(payload, secret)

        assert signature is not None
        assert len(signature) == 64  # SHA256 hex digest length

    def test_validate_signature_success(self):
        """Test successful signature validation."""
        payload = b'{"event": "test"}'
        secret = "test-secret-key"

        signature = generate_signature(payload, secret)
        result = validate_signature(payload, signature, secret)

        assert result is True

    def test_validate_signature_missing(self):
        """Test validation fails with missing signature."""
        payload = b'{"event": "test"}'

        with pytest.raises(HMACValidationError) as exc_info:
            validate_signature(payload, None, "secret")

        assert "Missing X-Signature header" in str(exc_info.value)

    def test_validate_signature_invalid(self):
        """Test validation fails with invalid signature."""
        payload = b'{"event": "test"}'

        with pytest.raises(HMACValidationError) as exc_info:
            validate_signature(payload, "invalid-signature", "secret")

        assert "Invalid signature" in str(exc_info.value)

    def test_validate_signature_wrong_secret(self):
        """Test validation fails with wrong secret."""
        payload = b'{"event": "test"}'

        signature = generate_signature(payload, "correct-secret")

        with pytest.raises(HMACValidationError):
            validate_signature(payload, signature, "wrong-secret")

    def test_signature_changes_with_payload(self):
        """Test that signature changes when payload changes."""
        secret = "test-secret"

        sig1 = generate_signature(b'{"a": 1}', secret)
        sig2 = generate_signature(b'{"a": 2}', secret)

        assert sig1 != sig2

    def test_signature_changes_with_secret(self):
        """Test that signature changes when secret changes."""
        payload = b'{"event": "test"}'

        sig1 = generate_signature(payload, "secret1")
        sig2 = generate_signature(payload, "secret2")

        assert sig1 != sig2
