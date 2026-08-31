from __future__ import annotations

import hashlib
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from api import contract_auth

UNAVAILABLE_DETAIL = "Private contract is not configured."


@pytest.mark.parametrize(
    "length",
    [
        contract_auth.MIN_API_TOKEN_LENGTH,
        contract_auth.MAX_API_TOKEN_LENGTH,
    ],
)
def test_bounded_visible_ascii_tokens_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    configured = "x" * length
    monkeypatch.setenv("DASHAFLOW_API_TOKEN", configured)

    contract_auth.require_api_token(
        f"Bearer {configured}",
        unavailable_detail=UNAVAILABLE_DETAIL,
    )


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Bearer wrong-token",
        f"Basic {'x' * contract_auth.MIN_API_TOKEN_LENGTH}",
        f"Bearer {'x' * (contract_auth.MAX_API_TOKEN_LENGTH + 1)}",
        f"Bearer {'x' * (contract_auth.MIN_API_TOKEN_LENGTH - 1)}",
    ],
)
def test_rejected_credentials_still_use_fixed_length_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    configured = "x" * contract_auth.MIN_API_TOKEN_LENGTH
    monkeypatch.setenv("DASHAFLOW_API_TOKEN", configured)
    real_compare_digest = contract_auth.hmac.compare_digest
    compare_digest = Mock(side_effect=real_compare_digest)
    monkeypatch.setattr(contract_auth.hmac, "compare_digest", compare_digest)

    with pytest.raises(HTTPException) as exc_info:
        contract_auth.require_api_token(
            authorization,
            unavailable_detail=UNAVAILABLE_DETAIL,
        )

    assert exc_info.value.status_code == 401
    compare_digest.assert_called_once()
    supplied_digest, expected_digest = compare_digest.call_args.args
    assert isinstance(supplied_digest, bytes)
    assert isinstance(expected_digest, bytes)
    assert len(supplied_digest) == hashlib.sha256().digest_size
    assert len(expected_digest) == hashlib.sha256().digest_size
