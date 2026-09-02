from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from api import index, profile

PROFILE_PATH = "/v1/profile/derive"
TOKEN = "test-sidecar-token-0123456789abcdef"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}
VALID_REQUEST = {
    "date_of_birth": "1990-04-15",
    "time_of_birth": "14:30",
    "latitude": 17.385,
    "longitude": 78.4867,
    "timezone": "Asia/Kolkata",
}

_SOURCE_PLANETS = (
    ("Sun", "Aries", 1.25, 6, False),
    ("Moon", "Aquarius", 2.5, 4, False),
    ("Mars", "Gemini", 3.75, 8, True),
    ("Mercury", "Cancer", 4.0, 9, False),
    ("Jupiter", "Leo", 5.25, 10, False),
    ("Venus", "Virgo", 6.5, 11, True),
    ("Saturn", "Libra", 7.75, 12, False),
    ("Rahu", "Scorpio", 8.0, 1, True),
    ("Ketu", "Taurus", 8.0, 7, True),
)

_MOON_FACTS = {
    "Ashwini": ("Aries", 1.25, 6, 1),
    "Dhanishta": ("Aquarius", 2.5, 4, 3),
}


def chart_fixture(nakshatra: str = "Dhanishta") -> dict:
    planets = {
        name: {
            "sign": sign,
            "degree": degree,
            "house": house,
            "is_retrograde": retrograde,
            "unpublished_detail": "must-not-cross-the-contract",
        }
        for name, sign, degree, house, retrograde in _SOURCE_PLANETS
    }
    moon_sign, moon_degree, moon_house, pada = _MOON_FACTS[nakshatra]
    planets["Moon"].update(
        {
            "sign": moon_sign,
            "degree": moon_degree,
            "house": moon_house,
            "nakshatra": nakshatra,
            "pada": pada,
        }
    )
    return {
        "metadata": {
            "dob": "raw-birth-date-must-not-be-returned",
            "time": "raw-birth-time-must-not-be-returned",
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
    return TestClient(index.app)


def mock_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    nakshatra: str = "Dhanishta",
    return_flags: int | None = None,
) -> Mock:
    calculate = Mock(return_value=chart_fixture(nakshatra))
    monkeypatch.setattr(profile.dashaflow, "calculate_vedic_chart", calculate)
    monkeypatch.setattr(
        profile.swe,
        "calc_ut",
        Mock(
            return_value=(
                (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
                profile.swe.FLG_MOSEPH if return_flags is None else return_flags,
            )
        ),
    )
    return calculate


@pytest.mark.parametrize(
    (
        "nakshatra",
        "return_flags",
        "expected_nakshatra",
        "expected_pada",
        "expected_rashi",
        "expected_degree",
        "expected_house",
        "expected_ephemeris",
    ),
    [
        (
            "Ashwini",
            profile.swe.FLG_SWIEPH,
            "Ashvini",
            1,
            "Mesha",
            1.25,
            6,
            "swiss",
        ),
        (
            "Dhanishta",
            profile.swe.FLG_MOSEPH,
            "Dhanishtha",
            3,
            "Kumbha",
            2.5,
            4,
            "moshier",
        ),
        (
            "Dhanishta",
            profile.swe.FLG_JPLEPH,
            "Dhanishtha",
            3,
            "Kumbha",
            2.5,
            4,
            "unknown",
        ),
    ],
)
def test_success_projects_only_the_versioned_canonical_contract(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    nakshatra: str,
    return_flags: int,
    expected_nakshatra: str,
    expected_pada: int,
    expected_rashi: str,
    expected_degree: float,
    expected_house: int,
    expected_ephemeris: str,
) -> None:
    calculate = mock_success(
        monkeypatch,
        nakshatra=nakshatra,
        return_flags=return_flags,
    )

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.json() == {
        "contract_version": "1.0",
        "engine": {
            "name": "DashaFlow",
            "version": "1.1.0",
            "ayanamsha": "Lahiri",
            "ephemeris": expected_ephemeris,
        },
        "data": {
            "nakshatra": expected_nakshatra,
            "pada": expected_pada,
            "janma_rashi": expected_rashi,
            "lagna": "Vrischika",
            "lagna_degree": 12.5,
            "planets": [
                {"name": "Surya", "rashi": "Mesha", "degree": 1.25, "house": 6, "retrograde": False},
                {"name": "Chandra", "rashi": expected_rashi, "degree": expected_degree, "house": expected_house, "retrograde": False},
                {"name": "Kuja", "rashi": "Mithuna", "degree": 3.75, "house": 8, "retrograde": True},
                {"name": "Budha", "rashi": "Karka", "degree": 4.0, "house": 9, "retrograde": False},
                {"name": "Guru", "rashi": "Simha", "degree": 5.25, "house": 10, "retrograde": False},
                {"name": "Shukra", "rashi": "Kanya", "degree": 6.5, "house": 11, "retrograde": True},
                {"name": "Shani", "rashi": "Tula", "degree": 7.75, "house": 12, "retrograde": False},
                {"name": "Rahu", "rashi": "Vrischika", "degree": 8.0, "house": 1, "retrograde": True},
                {"name": "Ketu", "rashi": "Vrishabha", "degree": 8.0, "house": 7, "retrograde": True},
            ],
        },
    }
    calculate.assert_called_once_with(
        "1990-04-15",
        "14:30",
        17.385,
        78.4867,
        "Asia/Kolkata",
    )
    assert "raw-birth" not in response.text
    assert "unpublished_detail" not in response.text
    assert "dashas" not in response.text


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        f"Basic {TOKEN}",
        "Bearer",
        "Bearer wrong-token",
        f"Bearer  {TOKEN}",
        f"Bearer {TOKEN} trailing",
        f"Bearer {TOKEN}{'x' * 256}",
    ],
)
def test_endpoint_rejects_missing_or_invalid_bearer_auth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    calculate = mock_success(monkeypatch)
    headers = {"Authorization": authorization} if authorization is not None else {}

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


@pytest.mark.parametrize(
    "configured",
    [
        None,
        "",
        "x" * 31,
        "x" * 257,
        " token-with-spaces ",
        "töken" * 8,
        ("x" * 31) + "\x7f",
    ],
)
def test_missing_or_misconfigured_server_token_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    configured: str | None,
) -> None:
    if configured is None:
        monkeypatch.delenv("DASHAFLOW_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("DASHAFLOW_API_TOKEN", configured)
    calculate = mock_success(monkeypatch)
    client = TestClient(index.app)

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 503
    assert response.json() == {"detail": "Profile derivation is not configured."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


@pytest.mark.parametrize(
    "replacement",
    [
        {"date_of_birth": "1990-4-15"},
        {"date_of_birth": "2023-02-29"},
        {"date_of_birth": "9999-01-01"},
        {"time_of_birth": "24:00"},
        {"time_of_birth": "14:30:00"},
        {"latitude": 90.0001},
        {"latitude": "17.385"},
        {"longitude": -180.0001},
        {"timezone": "Mars/Olympus"},
        {"timezone": " Asia/Kolkata"},
        {"unexpected_private_field": "must-not-be-echoed"},
    ],
)
def test_input_validation_is_strict_and_does_not_echo_values(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict,
) -> None:
    calculate = mock_success(monkeypatch)
    request = deepcopy(VALID_REQUEST)
    request.update(replacement)

    response = client.post(PROFILE_PATH, json=request, headers=AUTHORIZATION)

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
        PROFILE_PATH,
        content='{"date_of_birth":"private-invalid-json"',
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "private-invalid-json" not in response.text
    calculate.assert_not_called()


def test_unauthenticated_profile_body_is_rejected_before_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)

    response = client.post(
        PROFILE_PATH,
        content='{"date_of_birth":"private-invalid-json"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "private-invalid-json" not in response.text
    calculate.assert_not_called()


def test_authenticated_oversized_profile_body_is_rejected_before_projection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    private_marker = "private-oversized-profile-body"
    body = '{"padding":"' + private_marker + ('x' * 17_000) + '"}'

    response = client.post(
        PROFILE_PATH,
        content=body,
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert private_marker not in response.text
    calculate.assert_not_called()


@pytest.mark.parametrize(
    "replacement",
    [
        {
            "date_of_birth": "2024-11-03",
            "time_of_birth": "01:30",
            "timezone": "America/New_York",
        },
        {
            "date_of_birth": "2024-03-10",
            "time_of_birth": "02:30",
            "timezone": "America/New_York",
        },
    ],
)
def test_ambiguous_and_nonexistent_local_times_fail_closed(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    replacement: dict,
) -> None:
    calculate = mock_success(monkeypatch)
    request = deepcopy(VALID_REQUEST)
    request.update(replacement)

    response = client.post(PROFILE_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert not any(str(value) in response.text for value in replacement.values())
    calculate.assert_not_called()


def test_future_date_uses_the_supplied_birthplace_timezone(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UTC-calendar date can still be tomorrow at the birthplace."""

    calculate = mock_success(monkeypatch)
    monkeypatch.setattr(
        profile,
        "_utc_now",
        lambda: datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc),
    )
    request = {
        **VALID_REQUEST,
        "date_of_birth": "2026-09-01",
        "timezone": "America/Los_Angeles",
    }

    response = client.post(PROFILE_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid request."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_not_called()


def test_current_birthplace_date_is_allowed_across_the_utc_date_line(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The birthplace can already be on the next date while UTC is not."""

    calculate = mock_success(monkeypatch)
    monkeypatch.setattr(
        profile,
        "_utc_now",
        lambda: datetime(2026, 8, 31, 10, 30, tzinfo=timezone.utc),
    )
    request = {
        **VALID_REQUEST,
        "date_of_birth": "2026-09-01",
        "timezone": "Pacific/Kiritimati",
    }

    response = client.post(PROFILE_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 200
    assert response.json()["contract_version"] == "1.0"
    calculate.assert_called_once_with(
        "2026-09-01",
        "14:30",
        17.385,
        78.4867,
        "Pacific/Kiritimati",
    )


def test_engine_exception_is_not_returned_or_logged_by_the_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_exception = "private birth details from engine exception"
    calculate = Mock(side_effect=RuntimeError(private_exception))
    monkeypatch.setattr(profile.dashaflow, "calculate_vedic_chart", calculate)

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
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
    monkeypatch.setattr(profile.dashaflow, "calculate_vedic_chart", calculate)
    monkeypatch.setattr(
        profile.swe,
        "calc_ut",
        Mock(return_value=((0.0,), profile.swe.FLG_MOSEPH)),
    )

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "not-a-rashi" not in response.text
    calculate.assert_called_once()


@pytest.mark.parametrize(
    ("field", "value", "matching_house"),
    [
        ("nakshatra", "Shatabhisha", 4),
        ("pada", 4, 4),
        ("sign", "Capricorn", 3),
    ],
    ids=["nakshatra", "pada", "rashi"],
)
def test_profile_projection_rejects_incoherent_moon_birth_facts(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str | int,
    matching_house: int,
) -> None:
    calculate = mock_success(monkeypatch)
    chart = chart_fixture()
    chart["planets"]["Moon"][field] = value
    chart["planets"]["Moon"]["house"] = matching_house
    calculate.return_value = chart

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_called_once()


def test_profile_projection_rejects_non_whole_sign_house(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    chart = chart_fixture()
    chart["planets"]["Mars"]["house"] = 9
    calculate.return_value = chart

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_called_once()


def test_profile_projection_rejects_non_opposite_nodes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    chart = chart_fixture()
    chart["planets"]["Ketu"]["degree"] = 8.02
    calculate.return_value = chart

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_called_once()


def test_profile_projection_rejects_non_hundredth_degree(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    chart = chart_fixture()
    chart["planets"]["Sun"]["degree"] = 1.234
    calculate.return_value = chart

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 502
    assert response.json() == {"detail": "Profile derivation failed."}
    assert response.headers["Cache-Control"] == "private, no-store"
    calculate.assert_called_once()


def test_profile_projection_accepts_engine_rounded_sign_boundary(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = chart_fixture()
    chart['lagna']['degree'] = 30.0
    chart['planets']['Moon']['degree'] = 30.0
    chart['planets']['Moon']['nakshatra'] = 'Purva Bhadrapada'
    chart['planets']['Moon']['pada'] = 3
    monkeypatch.setattr(
        profile.dashaflow,
        'calculate_vedic_chart',
        Mock(return_value=chart),
    )
    monkeypatch.setattr(
        profile.swe,
        'calc_ut',
        Mock(return_value=((0.0,), profile.swe.FLG_SWIEPH)),
    )

    response = client.post(PROFILE_PATH, json=VALID_REQUEST, headers=AUTHORIZATION)

    assert response.status_code == 200
    data = response.json()['data']
    assert data['lagna'] == 'Vrischika'
    assert 29.99 < data['lagna_degree'] < 30
    moon = next(
        planet for planet in data['planets']
        if planet['name'] == 'Chandra'
    )
    assert moon['rashi'] == 'Kumbha'
    assert 29.99 < moon['degree'] < 30


def test_legacy_routes_remain_unauthenticated_and_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DASHAFLOW_API_TOKEN", raising=False)
    calculate = Mock(return_value={"legacy": "chart"})
    transit = Mock(return_value={"legacy": "transit"})
    career = Mock(return_value={"legacy": "career"})
    compatibility = Mock(return_value={"legacy": "compatibility"})
    muhurtha = Mock(
        return_value={
            "total_positive": 1,
            "total_negative": 0,
            "verdict": "auspicious",
            "positive_factors": ["legacy"],
        }
    )
    monkeypatch.setattr(index.dashaflow, "calculate_vedic_chart", calculate)
    monkeypatch.setattr(index.dashaflow, "cast_transit", transit)
    monkeypatch.setattr(index.dashaflow, "analyze_career", career)
    monkeypatch.setattr(index.dashaflow, "calculate_compatibility", compatibility)
    monkeypatch.setattr(index.dashaflow, "check_muhurtha", muhurtha)
    client = TestClient(index.app)

    health_response = client.get("/health")
    calculate_response = client.post("/calculate", json=VALID_REQUEST)
    transit_response = client.post(
        "/transit",
        json={**VALID_REQUEST, "transit_date": "2026-08-29"},
    )
    career_response = client.post("/career", json=VALID_REQUEST)
    compatibility_response = client.post(
        "/compatibility",
        json={"p1": VALID_REQUEST, "p2": VALID_REQUEST},
    )
    muhurtha_response = client.post(
        "/muhurtha",
        json={
            "birth_data": VALID_REQUEST,
            "current_location_data": VALID_REQUEST,
            "event_type": "General",
            "start_date": "2026-08-29",
            "end_date": "2026-08-29",
        },
    )

    assert health_response.status_code == 200
    assert calculate_response.json() == {"status": "ok", "data": {"legacy": "chart"}}
    assert transit_response.json() == {
        "status": "ok",
        "data": {"legacy": "transit"},
        "transit_date": "2026-08-29",
    }
    assert career_response.json() == {"status": "ok", "data": {"legacy": "career"}}
    assert compatibility_response.json() == {
        "status": "ok",
        "data": {"legacy": "compatibility"},
    }
    assert muhurtha_response.json() == {
        "status": "ok",
        "data": {
            "timings": [
                {
                    "date": "2026-08-29",
                    "start_time": "09:00",
                    "end_time": "12:00",
                    "points": ["legacy"],
                }
            ]
        },
    }
    for response in (
        health_response,
        calculate_response,
        transit_response,
        career_response,
        compatibility_response,
        muhurtha_response,
    ):
        assert response.status_code == 200
        assert "Cache-Control" not in response.headers
