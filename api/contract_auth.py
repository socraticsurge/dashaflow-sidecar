"""Shared fail-closed bearer-token validation for private v1 contracts."""

from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, status

MIN_API_TOKEN_LENGTH = 32
MAX_API_TOKEN_LENGTH = 256


def _is_valid_token_value(value: str) -> bool:
    """Accept only bounded visible ASCII suitable for an HTTP bearer token."""

    return (
        MIN_API_TOKEN_LENGTH <= len(value) <= MAX_API_TOKEN_LENGTH
        and value.isascii()
        and all("!" <= char <= "~" for char in value)
    )


def _token_digest(value: str) -> bytes:
    """Return a fixed-length value for timing-safe credential comparison."""

    return hashlib.sha256(value.encode("ascii")).digest()


def require_api_token(
    authorization: str | None,
    *,
    unavailable_detail: str,
) -> None:
    expected = os.environ.get("DASHAFLOW_API_TOKEN")
    if not expected or not _is_valid_token_value(expected):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )

    raw_authorization = authorization or ""
    header_is_bounded = len(raw_authorization) <= (
        len("Bearer ") + MAX_API_TOKEN_LENGTH
    )
    scheme, separator, supplied = (
        raw_authorization.partition(" ") if header_is_bounded else ("", "", "")
    )
    valid_shape = (
        header_is_bounded
        and separator == " "
        and scheme.casefold() == "bearer"
        and _is_valid_token_value(supplied)
    )

    # Hashing both inputs gives compare_digest equal-length byte strings even
    # when a caller supplies a credential with a different length. Invalid
    # shapes use a safe placeholder but still take the same comparison path.
    comparison_value = supplied if valid_shape else ""
    token_matches = hmac.compare_digest(
        _token_digest(comparison_value),
        _token_digest(expected),
    )
    if not valid_shape or not token_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
            headers={"WWW-Authenticate": "Bearer"},
        )
