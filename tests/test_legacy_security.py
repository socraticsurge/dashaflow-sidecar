"""Security and resource-bound contracts for legacy calculation routes."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api import index

TOKEN = "test-sidecar-token-0123456789abcdef"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}
BIRTH_DATA = {
    "date_of_birth": "1990-04-15",
    "time_of_birth": "14:30",
    "latitude": 17.385,
    "longitude": 78.4867,
    "timezone": "Asia/Kolkata",
}
LEGACY_REQUESTS = (
    ("/calculate", BIRTH_DATA),
    ("/transit", {**BIRTH_DATA, "transit_date": "2026-09-03"}),
    ("/career", BIRTH_DATA),
    ("/compatibility", {"p1": BIRTH_DATA, "p2": BIRTH_DATA}),
    (
        "/muhurtha",
        {
            "current_location_data": BIRTH_DATA,
            "event_type": "General",
            "start_date": "2026-09-03",
            "end_date": "2026-09-03",
        },
    ),
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DASHAFLOW_API_TOKEN", TOKEN)
    return TestClient(index.app)


@pytest.mark.parametrize(("path", "payload"), LEGACY_REQUESTS)
def test_every_legacy_calculation_rejects_missing_credentials_before_parsing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    calculate = Mock(side_effect=AssertionError("engine must not run"))
    monkeypatch.setattr(index.dashaflow, "calculate_vedic_chart", calculate)

    response = client.post(
        path,
        content='{"private-invalid-json"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


@pytest.mark.parametrize(("path", "payload"), LEGACY_REQUESTS)
def test_every_legacy_calculation_fails_closed_without_server_token(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    payload: dict,
) -> None:
    monkeypatch.delenv("DASHAFLOW_API_TOKEN", raising=False)

    response = TestClient(index.app).post(path, json=payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "Calculation service is not configured."}
    assert response.headers["Cache-Control"] == "private, no-store"


@pytest.mark.parametrize(("path", "payload"), LEGACY_REQUESTS)
def test_every_legacy_calculation_has_a_preparse_body_ceiling(
    client: TestClient,
    path: str,
    payload: dict,
) -> None:
    marker = "private-oversized-legacy-body"
    body = '{"padding":"' + marker + ("x" * 17_000) + '"}'

    response = client.post(
        path,
        content=body,
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert marker not in response.text


def test_chunked_legacy_body_has_the_same_preparse_ceiling(
    client: TestClient,
) -> None:
    marker = "private-streamed-legacy-body"
    chunks = iter(
        [
            b'{"padding":"',
            marker.encode("utf-8"),
            b"x" * 17_000,
            b'"}',
        ]
    )

    response = client.post(
        "/calculate",
        content=chunks,
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert marker not in response.text


def test_legacy_validation_and_engine_errors_are_sanitized(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = "private dependency diagnostic"
    calculate = Mock(side_effect=RuntimeError(marker))
    monkeypatch.setattr(index.dashaflow, "calculate_vedic_chart", calculate)

    validation_response = client.post(
        "/calculate",
        json={**BIRTH_DATA, "unexpected": marker},
        headers=AUTHORIZATION,
    )
    engine_response = client.post(
        "/calculate",
        json=BIRTH_DATA,
        headers=AUTHORIZATION,
    )

    assert validation_response.status_code == 422
    assert validation_response.json() == {"detail": "Invalid request."}
    assert marker not in validation_response.text
    assert engine_response.status_code == 502
    assert engine_response.json() == {"detail": "Calculation failed."}
    assert marker not in engine_response.text
    assert engine_response.headers["Cache-Control"] == "private, no-store"


def test_muhurtha_accepts_exact_maximum_window_without_unused_birth_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    check = Mock(
        return_value={
            "total_positive": 0,
            "total_negative": 1,
            "verdict": "inauspicious",
            "positive_factors": [],
        }
    )
    monkeypatch.setattr(index.dashaflow, "check_muhurtha", check)

    response = client.post(
        "/muhurtha",
        json={
            "current_location_data": BIRTH_DATA,
            "event_type": "General",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        },
        headers=AUTHORIZATION,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data": {"timings": []}}
    assert check.call_count == index.MAX_MUHURTHA_DAYS


@pytest.mark.parametrize(
    ("start_date", "end_date", "expected_detail"),
    [
        (
            "2026-01-01",
            "2026-02-01",
            "Muhurtha date window cannot exceed 31 days.",
        ),
        ("2026-01-02", "2026-01-01", "Invalid Muhurtha date window."),
        ("not-a-date", "2026-01-01", "Invalid Muhurtha date window."),
    ],
)
def test_muhurtha_rejects_unbounded_reversed_and_invalid_windows(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    start_date: str,
    end_date: str,
    expected_detail: str,
) -> None:
    check = Mock(side_effect=AssertionError("engine must not run"))
    monkeypatch.setattr(index.dashaflow, "check_muhurtha", check)

    response = client.post(
        "/muhurtha",
        json={
            "current_location_data": BIRTH_DATA,
            "start_date": start_date,
            "end_date": end_date,
        },
        headers=AUTHORIZATION,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}
    assert response.headers["Cache-Control"] == "private, no-store"
    check.assert_not_called()


def test_sidecar_exposes_no_browser_cors_policy(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        index.dashaflow,
        "calculate_vedic_chart",
        Mock(return_value={"legacy": "chart"}),
    )

    response = client.post(
        "/calculate",
        json=BIRTH_DATA,
        headers={**AUTHORIZATION, "Origin": "https://untrusted.example"},
    )

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
