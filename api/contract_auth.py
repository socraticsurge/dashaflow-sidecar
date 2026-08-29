"""Shared fail-closed bearer-token validation for private v1 contracts."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, status


def require_api_token(
    authorization: str | None,
    *,
    unavailable_detail: str,
) -> None:
    expected = os.environ.get("DASHAFLOW_API_TOKEN")
    if (
        not expected
        or not expected.isascii()
        or expected != expected.strip()
        or any(char.isspace() for char in expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )

    scheme, separator, supplied = (authorization or "").partition(" ")
    valid_shape = (
        separator == " "
        and scheme.casefold() == "bearer"
        and bool(supplied)
        and supplied.isascii()
        and not any(char.isspace() for char in supplied)
    )
    if not valid_shape or not hmac.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized.",
            headers={"WWW-Authenticate": "Bearer"},
        )
