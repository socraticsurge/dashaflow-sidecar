from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock, call

import pytest
from fastapi.testclient import TestClient

from api import election_chart, index

ELECTION_PATH = "/v1/election-chart/derive"
TOKEN = "test-sidecar-token"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}
FIXED_NOW = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
VALID_REQUEST = {
    "contract_version": "1.0",
    "location": {
        "latitude": 17.385,
        "longitude": 78.4867,
        "timezone": "Asia/Kolkata",
    },
    "instants": [
        "2026-09-08T05:29:00.000Z",
        "2026-09-08T06:19:00+00:00",
    ],
}

_SOURCE_PLANETS = (
    ("Sun", "Aries", 1.25, False),
    ("Moon", "Taurus", 2.5, False),
    ("Mars", "Gemini", 3.75, True),
    ("Mercury", "Cancer", 4.0, False),
    ("Jupiter", "Leo", 5.25, False),
    ("Venus", "Virgo", 6.5, True),
    ("Saturn", "Libra", 7.75, False),
    ("Rahu", "Scorpio", 8.0, True),
    ("Ketu", "Sagittarius", 9.25, True),
)


def chart_fixture() -> dict:
    planets = {
        name: {
            "sign": sign,
            "degree": degree,
            # Deliberately wrong but structurally valid. The contract must derive
            # whole-sign houses rather than trusting an unpublished engine field.
            "house": 12,
            "is_retrograde": retrograde,
            "unpublished_detail": "must-not-cross-the-contract",
        }
        for name, sign, degree, retrograde in _SOURCE_PLANETS
    }
    planets["Moon"].update({"nakshatra": "Dhanishta", "pada": 3})
    return {
        "metadata": {
            "dob": "raw-event-date-must-not-be-returned",
            "time": "raw-event-time-must-not-be-returned",
            "coordinates": {"lat": 17.385, "lon": 78.4867},
            "timezone": "Asia/Kolkata",
            "ayanamsha": "Lahiri",
        },
        "lagna": {
            "sign": "Scorpio",
            "degree": 12.5,
            "unpublished_detail": "must-not-cross-the-contract",
        },
        "planets": planets,
        "dashas": {"private": "not-in-contract"},
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("DASHAFLOW_API_TOKEN", TOKEN)
    monkeypatch.setattr(election_chart, "_utc_now", lambda: FIXED_NOW)
    return TestClient(index.app)


def mock_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ephemerides: tuple[str, ...] = ("swiss", "moshier"),
) -> Mock:
    calculate = Mock(side_effect=[chart_fixture() for _ in ephemerides])
    monkeypatch.setattr(
        election_chart.dashaflow,
        "calculate_vedic_chart",
        calculate,
    )
    monkeypatch.setattr(
        election_chart,
        "_ephemeris_used_for_local_time",
        Mock(side_effect=ephemerides),
    )
    return calculate


def test_success_returns_ordered_minimal_whole_sign_snapshots(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)

    response = client.post(
        ELECTION_PATH,
        json=VALID_REQUEST,
        headers=AUTHORIZATION,
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {
        "contract_version": "1.0",
        "location": {
            "latitude": 17.385,
            "longitude": 78.4867,
            "timezone": "Asia/Kolkata",
        },
        "engine": {
            "name": "DashaFlow",
            "version": "1.1.0",
            "ayanamsha": "Lahiri",
            "ephemeris": "mixed",
        },
        "house_system": "whole_sign",
        "data": {
            "charts": [
                {
                    "instant": "2026-09-08T05:29:00.000Z",
                    "lagna": {"rashi": "Vrischika", "degree": 12.5},
                    "planets": [
                        {
                            "name": "Surya",
                            "rashi": "Mesha",
                            "degree": 1.25,
                            "house": 6,
                            "retrograde": False,
                        },
                        {
                            "name": "Chandra",
                            "rashi": "Vrishabha",
                            "degree": 2.5,
                            "house": 7,
                            "retrograde": False,
                        },
                        {
                            "name": "Kuja",
                            "rashi": "Mithuna",
                            "degree": 3.75,
                            "house": 8,
                            "retrograde": True,
                        },
                        {
                            "name": "Budha",
                            "rashi": "Karka",
                            "degree": 4.0,
                            "house": 9,
                            "retrograde": False,
                        },
                        {
                            "name": "Guru",
                            "rashi": "Simha",
                            "degree": 5.25,
                            "house": 10,
                            "retrograde": False,
                        },
                        {
                            "name": "Shukra",
                            "rashi": "Kanya",
                            "degree": 6.5,
                            "house": 11,
                            "retrograde": True,
                        },
                        {
                            "name": "Shani",
                            "rashi": "Tula",
                            "degree": 7.75,
                            "house": 12,
                            "retrograde": False,
                        },
                        {
                            "name": "Rahu",
                            "rashi": "Vrischika",
                            "degree": 8.0,
                            "house": 1,
                            "retrograde": True,
                        },
                        {
                            "name": "Ketu",
                            "rashi": "Dhanu",
                            "degree": 9.25,
                            "house": 2,
                            "retrograde": True,
                        },
                    ],
                },
                {
                    "instant": "2026-09-08T06:19:00+00:00",
                    "lagna": {"rashi": "Vrischika", "degree": 12.5},
                    "planets": [
                        {
                            "name": "Surya",
                            "rashi": "Mesha",
                            "degree": 1.25,
                            "house": 6,
                            "retrograde": False,
                        },
                        {
                            "name": "Chandra",
                            "rashi": "Vrishabha",
                            "degree": 2.5,
                            "house": 7,
                            "retrograde": False,
                        },
                        {
                            "name": "Kuja",
                            "rashi": "Mithuna",
                            "degree": 3.75,
                            "house": 8,
                            "retrograde": True,
                        },
                        {
                            "name": "Budha",
                            "rashi": "Karka",
                            "degree": 4.0,
                            "house": 9,
                            "retrograde": False,
                        },
                        {
                            "name": "Guru",
                            "rashi": "Simha",
                            "degree": 5.25,
                            "house": 10,
                            "retrograde": False,
                        },
                        {
                            "name": "Shukra",
                            "rashi": "Kanya",
                            "degree": 6.5,
                            "house": 11,
                            "retrograde": True,
                        },
                        {
                            "name": "Shani",
                            "rashi": "Tula",
                            "degree": 7.75,
                            "house": 12,
                            "retrograde": False,
                        },
                        {
                            "name": "Rahu",
                            "rashi": "Vrischika",
                            "degree": 8.0,
                            "house": 1,
                            "retrograde": True,
                        },
                        {
                            "name": "Ketu",
                            "rashi": "Dhanu",
                            "degree": 9.25,
                            "house": 2,
                            "retrograde": True,
                        },
                    ],
                },
            ],
        },
    }
    assert calculate.call_args_list == [
        call("2026-09-08", "10:59", 17.385, 78.4867, "Asia/Kolkata"),
        call("2026-09-08", "11:49", 17.385, 78.4867, "Asia/Kolkata"),
    ]
    assert "raw-event" not in response.text
    assert "unpublished_detail" not in response.text
    assert "dashas" not in response.text


def test_single_ephemeris_is_reported_without_mixed_marker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = deepcopy(VALID_REQUEST)
    request["instants"] = request["instants"][:1]
    mock_success(monkeypatch, ephemerides=("moshier",))

    response = client.post(ELECTION_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 200
    assert response.json()["engine"]["ephemeris"] == "moshier"
    assert len(response.json()["data"]["charts"]) == 1


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "Basic test-sidecar-token",
        "Bearer",
        "Bearer wrong-token",
        "Bearer  test-sidecar-token",
        "Bearer test-sidecar-token trailing",
    ],
)
def test_endpoint_rejects_missing_or_invalid_bearer_auth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    calculate = mock_success(monkeypatch)
    headers = {"Authorization": authorization} if authorization is not None else {}

    response = client.post(ELECTION_PATH, json=VALID_REQUEST, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


@pytest.mark.parametrize("configured", [None, "", " token-with-spaces ", "töken"])
def test_missing_or_misconfigured_server_token_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    if configured is None:
        monkeypatch.delenv("DASHAFLOW_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DASHAFLOW_API_TOKEN", configured)
    monkeypatch.setattr(election_chart, "_utc_now", lambda: FIXED_NOW)
    calculate = mock_success(monkeypatch)
    client = TestClient(index.app)

    response = client.post(ELECTION_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 503
    assert response.json() == {"detail": "Election chart derivation is not configured."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


@pytest.mark.parametrize(
    "replacement",
    [
        {"contract_version": "2.0"},
        {"contract_version": 1.0},
        {"unexpected_private_field": "must-not-be-echoed"},
        {"location": {**VALID_REQUEST["location"], "latitude": "17.385"}},
        {"location": {**VALID_REQUEST["location"], "latitude": 90.0001}},
        {"location": {**VALID_REQUEST["location"], "longitude": -180.0001}},
        {"location": {**VALID_REQUEST["location"], "timezone": "Mars/Olympus"}},
        {"location": {**VALID_REQUEST["location"], "timezone": " Asia/Kolkata"}},
        {"location": {**VALID_REQUEST["location"], "private": "no"}},
        {"instants": []},
        {"instants": ["2026-09-08T05:29:00Z"] * 25},
        {"instants": ["2026-09-08T05:29:00"]},
        {"instants": ["2026-09-08T05:29:01Z"]},
        {"instants": ["2026-09-08T05:29:00.001Z"]},
        {"instants": ["2026-09-08T05:29:00+24:00"]},
        {"instants": ["2026-02-29T05:29:00Z"]},
        {"instants": ["2025-08-27T23:59:00Z"]},
        {"instants": ["2031-09-10T00:00:00Z"]},
        {
            "instants": [
                "2026-09-08T05:29:00Z",
                "2026-09-08T10:59:00+05:30",
            ]
        },
    ],
)
def test_input_validation_is_strict_bounded_and_does_not_echo_values(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict,
) -> None:
    calculate = mock_success(monkeypatch)
    request = deepcopy(VALID_REQUEST)
    request.update(replacement)

    response = client.post(ELECTION_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert not any(str(value) in response.text for value in replacement.values())
    calculate.assert_not_called()


def test_invalid_json_uses_the_same_safe_error_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)

    response = client.post(
        ELECTION_PATH,
        content='{"instants":["private-invalid-json"',
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "private-invalid-json" not in response.text
    calculate.assert_not_called()


def test_engine_exception_is_not_returned_or_logged_by_the_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_exception = "private event details from engine exception"
    calculate = Mock(side_effect=RuntimeError(private_exception))
    monkeypatch.setattr(
        election_chart.dashaflow,
        "calculate_vedic_chart",
        calculate,
    )

    response = client.post(ELECTION_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Election chart derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert private_exception not in response.text
    assert private_exception not in caplog.text
    calculate.assert_called_once()


def test_malformed_engine_projection_fails_safely(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = chart_fixture()
    chart["planets"]["Moon"]["sign"] = "not-a-rashi"
    calculate = Mock(return_value=chart)
    monkeypatch.setattr(
        election_chart.dashaflow,
        "calculate_vedic_chart",
        calculate,
    )
    monkeypatch.setattr(
        election_chart,
        "_ephemeris_used_for_local_time",
        Mock(return_value="moshier"),
    )
    request = deepcopy(VALID_REQUEST)
    request["instants"] = request["instants"][:1]

    response = client.post(ELECTION_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Election chart derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "not-a-rashi" not in response.text
    calculate.assert_called_once()
