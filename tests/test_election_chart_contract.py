from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, call
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from api import election_chart, index

ELECTION_PATH = "/v1/election-chart/derive"
TOKEN = "test-sidecar-token-0123456789abcdef"
AUTHORIZATION = {"Authorization": f"Bearer {TOKEN}"}
FIXED_NOW = datetime(2026, 8, 29, 0, 0, tzinfo=timezone.utc)
REPOSITORY_CAPTURE_PATH = (
    Path(__file__).parent / "fixtures" / "election_chart_repository_capture.json"
)
DRIKPANCHANG_CAPTURE_PATH = (
    Path(__file__).parent / "fixtures" / "election_chart_drikpanchang_capture.json"
)
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


@pytest.fixture(scope="module")
def repository_capture() -> dict:
    return json.loads(REPOSITORY_CAPTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def drikpanchang_capture() -> dict:
    return json.loads(DRIKPANCHANG_CAPTURE_PATH.read_text(encoding="utf-8"))


def assert_chart_matches_repository_capture(
    actual: dict,
    expected: dict,
    *,
    degree_tolerance: float,
) -> None:
    assert actual["instant"] == expected["instant"]
    assert actual["lagna"]["rashi"] == expected["lagna"]["rashi"]
    assert actual["lagna"]["degree"] == pytest.approx(
        expected["lagna"]["degree"],
        abs=degree_tolerance,
    )

    planets = actual["planets"]
    expected_planets = expected["planets"]
    assert [planet["name"] for planet in planets] == expected_planets["names"]
    assert [planet["rashi"] for planet in planets] == expected_planets["rashis"]
    assert [planet["house"] for planet in planets] == expected_planets["houses"]
    assert [planet["retrograde"] for planet in planets] == expected_planets[
        "retrograde"
    ]
    assert [planet["degree"] for planet in planets] == pytest.approx(
        expected_planets["degrees"],
        abs=degree_tolerance,
    )


def test_real_engine_matches_drikpanchang_across_dates_and_cities(
    client: TestClient,
    drikpanchang_capture: dict,
) -> None:
    """Lock the sign-level election inputs to dated external references."""
    assert drikpanchang_capture["source_conventions"] == {
        "zodiac": "sidereal",
        "ayanamsha": "Lahiri/Chitra Paksha",
        "node_convention": "mean",
    }
    assert len({case["location"]["timezone"] for case in drikpanchang_capture["cases"]}) > 1

    for case in drikpanchang_capture["cases"]:
        response = client.post(
            ELECTION_PATH,
            json={
                "contract_version": "1.0",
                "location": case["location"],
                "instants": [case["instant"]],
            },
            headers=AUTHORIZATION,
        )
        assert response.status_code == 200, case["id"]
        contract = response.json()
        assert contract["engine"]["ayanamsha"] == "Lahiri"
        assert contract["engine"]["node_convention"] == "mean"
        chart = contract["data"]["charts"][0]
        expected = case["expected"]
        assert chart["lagna"]["rashi"] == expected["lagna"]["rashi"], case["id"]
        assert chart["lagna"]["degree"] == pytest.approx(
            expected["lagna"]["degree"], abs=0.30,
        ), case["id"]
        actual_planets = {planet["name"]: planet for planet in chart["planets"]}
        assert set(actual_planets) == set(expected["planets"])
        for name, expected_planet in expected["planets"].items():
            actual_planet = actual_planets[name]
            assert actual_planet["rashi"] == expected_planet["rashi"], (
                case["id"], name
            )
            assert actual_planet["degree"] == pytest.approx(
                expected_planet["degree"], abs=0.03,
            ), (case["id"], name)


def test_real_engine_preserves_documented_drik_lagna_boundary_differences(
    client: TestClient,
    drikpanchang_capture: dict,
) -> None:
    """Lock known differences so an interior comparison cannot imply identity."""
    assert "not passing Lagna-equivalence cases" in drikpanchang_capture[
        "boundary_scope"
    ]
    assert len(drikpanchang_capture["boundary_cases"]) == 2
    for case in drikpanchang_capture["boundary_cases"]:
        response = client.post(
            ELECTION_PATH,
            json={
                "contract_version": "1.0",
                "location": case["location"],
                "instants": [case["instant"]],
            },
            headers=AUTHORIZATION,
        )
        assert response.status_code == 200, case["id"]
        chart = response.json()["data"]["charts"][0]
        assert chart["lagna"]["rashi"] == case["expected_dashaflow_lagna"]
        assert chart["lagna"]["rashi"] != case["expected_drik_lagna"]
        actual_planets = {planet["name"]: planet for planet in chart["planets"]}
        for name, rashi in case["relevant_planet_rashis"].items():
            assert actual_planets[name]["rashi"] == rashi, (case["id"], name)


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
            "node_convention": "mean",
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
        call("2026-09-08", "05:29", 17.385, 78.4867, "UTC"),
        call("2026-09-08", "06:19", 17.385, 78.4867, "UTC"),
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


def test_repository_engine_capture_is_explicitly_not_external_validation(
    repository_capture: dict,
) -> None:
    metadata = repository_capture["metadata"]

    assert metadata["kind"] == "repository_engine_capture"
    assert "not independent" in metadata["validation_boundary"]
    assert metadata["degree_tolerance"] == 0.01
    assert len(metadata["limitations"]) >= 3


def test_repository_engine_capture_is_repeatable_across_locations_and_boundaries(
    client: TestClient,
    repository_capture: dict,
) -> None:
    tolerance = repository_capture["metadata"]["degree_tolerance"]

    for case in repository_capture["boundary_cases"]:
        first = client.post(
            ELECTION_PATH,
            json=case["request"],
            headers=AUTHORIZATION,
        )
        repeated = client.post(
            ELECTION_PATH,
            json=case["request"],
            headers=AUTHORIZATION,
        )

        assert first.status_code == 200, case["id"]
        assert repeated.status_code == 200, case["id"]
        assert repeated.json() == first.json(), case["id"]
        actual = first.json()
        assert actual["location"] == case["request"]["location"]
        assert actual["house_system"] == "whole_sign"
        assert actual["engine"] == {
            "name": "DashaFlow",
            "version": "1.1.0",
            "ayanamsha": "Lahiri",
            "ephemeris": case["expected"]["ephemeris"],
            "node_convention": "mean",
        }
        assert len(actual["data"]["charts"]) == len(case["expected"]["charts"])
        for actual_chart, expected_chart in zip(
            actual["data"]["charts"],
            case["expected"]["charts"],
            strict=True,
        ):
            assert_chart_matches_repository_capture(
                actual_chart,
                expected_chart,
                degree_tolerance=tolerance,
            )


def test_exact_utc_calculation_matches_unambiguous_local_engine_projection(
    repository_capture: dict,
) -> None:
    for case in repository_capture["boundary_cases"]:
        request = case["request"]
        requested_instant = request["instants"][0]
        instant = election_chart._parse_instant(requested_instant)
        local_instant = instant.astimezone(ZoneInfo(request["location"]["timezone"]))
        location = request["location"]

        utc_chart = election_chart.dashaflow.calculate_vedic_chart(
            instant.date().isoformat(),
            instant.strftime("%H:%M"),
            location["latitude"],
            location["longitude"],
            "UTC",
        )
        local_chart = election_chart.dashaflow.calculate_vedic_chart(
            local_instant.date().isoformat(),
            local_instant.strftime("%H:%M"),
            location["latitude"],
            location["longitude"],
            location["timezone"],
        )

        assert election_chart._project_whole_sign_snapshot(
            utc_chart,
            requested_instant,
        ) == election_chart._project_whole_sign_snapshot(
            local_chart,
            requested_instant,
        )
        assert election_chart._ephemeris_used_for_local_time(
            instant.date().isoformat(),
            instant.strftime("%H:%M"),
            "UTC",
        ) == election_chart._ephemeris_used_for_local_time(
            local_instant.date().isoformat(),
            local_instant.strftime("%H:%M"),
            location["timezone"],
        )


def test_exact_instants_disambiguate_both_sides_of_a_dst_fold(
    client: TestClient,
    repository_capture: dict,
) -> None:
    case = repository_capture["dst_fold_case"]
    instants = [
        election_chart._parse_instant(value).astimezone(ZoneInfo("America/New_York"))
        for value in case["request"]["instants"]
    ]
    assert [instant.strftime("%Y-%m-%d %H:%M") for instant in instants] == [
        "2026-11-01 01:30",
        "2026-11-01 01:30",
    ]
    assert [instant.utcoffset().total_seconds() for instant in instants] == [
        -4 * 60 * 60,
        -5 * 60 * 60,
    ]

    response = client.post(
        ELECTION_PATH,
        json=case["request"],
        headers=AUTHORIZATION,
    )

    assert response.status_code == 200
    actual = response.json()
    assert actual["location"] == case["request"]["location"]
    assert [chart["instant"] for chart in actual["data"]["charts"]] == case["request"][
        "instants"
    ]
    assert [chart["lagna"]["rashi"] for chart in actual["data"]["charts"]] == [
        expected["rashi"] for expected in case["expected_lagnas"]
    ]
    assert [chart["lagna"]["degree"] for chart in actual["data"]["charts"]] == (
        pytest.approx(
            [expected["degree"] for expected in case["expected_lagnas"]],
            abs=repository_capture["metadata"]["degree_tolerance"],
        )
    )
    assert actual["data"]["charts"][0] != actual["data"]["charts"][1]


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

    response = client.post(ELECTION_PATH, json=VALID_REQUEST, headers=headers)

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


def test_unauthenticated_invalid_body_is_rejected_before_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)

    response = client.post(
        ELECTION_PATH,
        content='{"instants":["private-invalid-json"',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized."}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert "private-invalid-json" not in response.text
    calculate.assert_not_called()


def test_authenticated_oversized_body_is_rejected_before_projection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    private_marker = "private-oversized-event-body"
    body = '{"padding":"' + private_marker + ('x' * 17_000) + '"}'

    response = client.post(
        ELECTION_PATH,
        content=body,
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert private_marker not in response.text
    calculate.assert_not_called()


def test_authenticated_chunked_oversized_body_gets_sanitized_413(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = mock_success(monkeypatch)
    private_marker = "private-streamed-event-body"
    chunks = iter([
        b'{"padding":"',
        private_marker.encode("utf-8"),
        b"x" * 17_000,
        b'"}',
    ])

    response = client.post(
        ELECTION_PATH,
        content=chunks,
        headers={**AUTHORIZATION, "Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body is too large."}
    assert response.headers["Cache-Control"] == "private, no-store"
    assert private_marker not in response.text
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


def test_rounded_thirty_degree_boundary_preserves_engine_sign(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chart = chart_fixture()
    chart['lagna']['degree'] = 30.0
    chart['planets']['Moon']['degree'] = 30.0
    monkeypatch.setattr(
        election_chart.dashaflow,
        'calculate_vedic_chart',
        Mock(return_value=chart),
    )
    monkeypatch.setattr(
        election_chart,
        '_ephemeris_used_for_local_time',
        Mock(return_value='swiss'),
    )
    request = deepcopy(VALID_REQUEST)
    request['instants'] = ['2026-09-09T22:59:00.000Z']

    response = client.post(ELECTION_PATH, json=request, headers=AUTHORIZATION)

    assert response.status_code == 200
    snapshot = response.json()['data']['charts'][0]
    assert snapshot['lagna']['rashi'] == 'Vrischika'
    assert 29.99 < snapshot['lagna']['degree'] < 30
    moon = next(
        planet for planet in snapshot['planets']
        if planet['name'] == 'Chandra'
    )
    assert moon['rashi'] == 'Vrishabha'
    assert 29.99 < moon['degree'] < 30
