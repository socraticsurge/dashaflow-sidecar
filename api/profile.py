"""Narrow, authenticated profile-derivation contract for trusted callers."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from typing import Any

import dashaflow
import pytz
import swisseph as swe
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    field_validator,
    model_validator,
)

from api.contract_auth import require_api_token


PROFILE_DERIVE_PATH = "/v1/profile/derive"
CONTRACT_VERSION = "1.0"

_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_TIME_PATTERN = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")

_NAKSHATRAS = (
    "Ashvini",
    "Bharani",
    "Krittika",
    "Rohini",
    "Mrigashira",
    "Ardra",
    "Punarvasu",
    "Pushya",
    "Ashlesha",
    "Magha",
    "Purva Phalguni",
    "Uttara Phalguni",
    "Hasta",
    "Chitra",
    "Swati",
    "Vishakha",
    "Anuradha",
    "Jyeshtha",
    "Mula",
    "Purva Ashadha",
    "Uttara Ashadha",
    "Shravana",
    "Dhanishtha",
    "Shatabhisha",
    "Purva Bhadrapada",
    "Uttara Bhadrapada",
    "Revati",
)
_NAKSHATRA_ALIASES = {name: name for name in _NAKSHATRAS}
_NAKSHATRA_ALIASES.update(
    {
        "Ashwini": "Ashvini",
        "Dhanishta": "Dhanishtha",
    }
)

_RASHI_NAMES = (
    "Mesha",
    "Vrishabha",
    "Mithuna",
    "Karka",
    "Simha",
    "Kanya",
    "Tula",
    "Vrischika",
    "Dhanu",
    "Makara",
    "Kumbha",
    "Meena",
)
_ENGLISH_RASHIS = (
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpio",
    "Sagittarius",
    "Capricorn",
    "Aquarius",
    "Pisces",
)
_RASHI_ALIASES = dict(zip(_ENGLISH_RASHIS, _RASHI_NAMES, strict=True))
_RASHI_ALIASES.update({name: name for name in _RASHI_NAMES})

_PLANETS = (
    ("Sun", "Surya"),
    ("Moon", "Chandra"),
    ("Mars", "Kuja"),
    ("Mercury", "Budha"),
    ("Jupiter", "Guru"),
    ("Venus", "Shukra"),
    ("Saturn", "Shani"),
    ("Rahu", "Rahu"),
    ("Ketu", "Ketu"),
)

_ROUNDED_DEGREE_HALF_STEP = 0.005
_ROUNDED_OPPOSITION_TOLERANCE = _ROUNDED_DEGREE_HALF_STEP * 2
_ANGLE_EPSILON = 1e-9
_HUNDREDTH_ALIGNMENT_EPSILON = 1e-9
_PADA_WIDTH = 360 / (len(_NAKSHATRAS) * 4)


def _utc_now() -> datetime:
    """Return an aware UTC clock value; kept injectable for boundary tests."""

    return datetime.now(timezone.utc)


class ProfileDeriveRequest(BaseModel):
    """Strict wire input; values are never copied into the response."""

    model_config = ConfigDict(extra="forbid", strict=True)

    date_of_birth: StrictStr = Field(min_length=10, max_length=10)
    time_of_birth: StrictStr = Field(min_length=5, max_length=5)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: StrictStr = Field(min_length=1, max_length=64)

    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, value: str) -> str:
        if not _DATE_PATTERN.fullmatch(value):
            raise ValueError("date must use YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("date must be a real calendar date") from exc
        return value

    @field_validator("time_of_birth")
    @classmethod
    def validate_time_of_birth(cls, value: str) -> str:
        if not _TIME_PATTERN.fullmatch(value):
            raise ValueError("time must use HH:MM in 24-hour time")
        # The pattern establishes the wire format; parsing confirms a real time.
        time.fromisoformat(value)
        return value

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("timezone must be an IANA identifier")
        try:
            pytz.timezone(value)
        except pytz.UnknownTimeZoneError as exc:
            raise ValueError("timezone must be an IANA identifier") from exc
        return value

    @model_validator(mode="after")
    def validate_local_birth_time(self) -> "ProfileDeriveRequest":
        birthplace_timezone = pytz.timezone(self.timezone)
        if date.fromisoformat(self.date_of_birth) > _utc_now().astimezone(
            birthplace_timezone
        ).date():
            raise ValueError("date must not be in the future")

        naive = datetime.combine(
            date.fromisoformat(self.date_of_birth),
            time.fromisoformat(self.time_of_birth),
        )
        try:
            birthplace_timezone.localize(naive, is_dst=None)
        except (pytz.AmbiguousTimeError, pytz.NonExistentTimeError) as exc:
            raise ValueError(
                "local birth time must identify one real instant"
            ) from exc
        return self


class _ProjectionError(Exception):
    """Raised when DashaFlow does not satisfy the versioned contract."""


def _require_api_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    require_api_token(
        authorization,
        unavailable_detail="Profile derivation is not configured.",
    )


def _record(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _ProjectionError
    return value


def _canonical_name(value: Any, aliases: Mapping[str, str]) -> str:
    if not isinstance(value, str):
        raise _ProjectionError
    try:
        return aliases[value]
    except KeyError as exc:
        raise _ProjectionError from exc


def _finite_degree(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _ProjectionError
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 30:
        raise _ProjectionError
    if (
        abs(result * 100 - round(result * 100))
        > _HUNDREDTH_ALIGNMENT_EPSILON
    ):
        raise _ProjectionError
    # DashaFlow 1.1.0 rounds a within-sign value to two decimals after it has
    # already selected the sign. Values from 29.995 degrees can therefore be
    # represented as exactly 30.0 with the still-correct preceding sign. Keep
    # that sign and normalize only this known rounded-boundary representation
    # to the largest finite value below 30; larger values remain malformed.
    if result == 30:
        return math.nextafter(30.0, 0.0)
    return result


def _house(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 12:
        raise _ProjectionError
    return value


def _pada(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
        raise _ProjectionError
    return value


def _absolute_longitude(rashi: str, degree: float) -> float:
    return _RASHI_NAMES.index(rashi) * 30 + degree


def _require_opposite_nodes(planets: list[dict[str, Any]]) -> None:
    rahu = planets[7]
    ketu = planets[8]
    if rahu["name"] != "Rahu" or ketu["name"] != "Ketu":
        raise _ProjectionError

    separation = (
        _absolute_longitude(ketu["rashi"], ketu["degree"])
        - _absolute_longitude(rahu["rashi"], rahu["degree"])
    ) % 360
    if (
        abs(separation - 180)
        > _ROUNDED_OPPOSITION_TOLERANCE + _ANGLE_EPSILON
    ):
        raise _ProjectionError


def _require_whole_sign_houses(
    lagna_rashi: str,
    planets: list[dict[str, Any]],
) -> None:
    lagna_index = _RASHI_NAMES.index(lagna_rashi)
    for planet in planets:
        expected_house = (
            _RASHI_NAMES.index(planet["rashi"]) - lagna_index
        ) % 12 + 1
        if planet["house"] != expected_house:
            raise _ProjectionError


def _project_moon_birth_facts(
    moon_source: Mapping[str, Any],
    moon: Mapping[str, Any],
) -> dict[str, Any]:
    nakshatra = _canonical_name(
        moon_source.get("nakshatra"),
        _NAKSHATRA_ALIASES,
    )
    pada = _pada(moon_source.get("pada"))
    janma_rashi = _canonical_name(moon_source.get("sign"), _RASHI_ALIASES)
    if moon.get("name") != "Chandra" or moon.get("rashi") != janma_rashi:
        raise _ProjectionError

    nakshatra_index = _NAKSHATRAS.index(nakshatra)
    rashi_index = _RASHI_NAMES.index(janma_rashi)
    pada_index = nakshatra_index * 4 + pada - 1
    if pada_index // 9 != rashi_index:
        raise _ProjectionError

    pada_start = pada_index * _PADA_WIDTH
    pada_end = (pada_index + 1) * _PADA_WIDTH
    rashi_start = rashi_index * 30
    possible_start = rashi_start + max(
        0,
        moon["degree"] - _ROUNDED_DEGREE_HALF_STEP,
    )
    possible_end = rashi_start + min(
        30,
        moon["degree"] + _ROUNDED_DEGREE_HALF_STEP,
    )
    if (
        possible_start > pada_end + _ANGLE_EPSILON
        or possible_end < pada_start - _ANGLE_EPSILON
    ):
        raise _ProjectionError

    return {
        "nakshatra": nakshatra,
        "pada": pada,
        "janma_rashi": janma_rashi,
    }


def _engine_version() -> str:
    value = getattr(dashaflow, "__version__", None)
    if not isinstance(value, str) or not value or len(value) > 40:
        return "unknown"
    return value


def _ephemeris_used_for_local_time(
    date_text: str,
    time_text: str,
    timezone_name: str,
) -> str:
    """Probe Swiss Ephemeris once and classify its actual returned flag."""

    try:
        naive_datetime = datetime.combine(
            date.fromisoformat(date_text),
            time.fromisoformat(time_text),
        )
        local_datetime = pytz.timezone(timezone_name).localize(
            naive_datetime,
            is_dst=None,
        )
        utc_datetime = local_datetime.astimezone(timezone.utc)
        utc_hour = (
            utc_datetime.hour
            + utc_datetime.minute / 60.0
            + utc_datetime.second / 3600.0
        )
        julian_day = swe.julday(
            utc_datetime.year,
            utc_datetime.month,
            utc_datetime.day,
            utc_hour,
        )
        swe.set_sid_mode(swe.SIDM_LAHIRI)
        _, return_flags = swe.calc_ut(
            julian_day,
            swe.SUN,
            swe.FLG_SIDEREAL | swe.FLG_SPEED,
        )
    except Exception:
        return "unknown"

    if not isinstance(return_flags, int):
        return "unknown"
    if return_flags & swe.FLG_MOSEPH:
        return "moshier"
    if return_flags & swe.FLG_SWIEPH:
        return "swiss"
    return "unknown"


def _ephemeris_used(data: ProfileDeriveRequest) -> str:
    return _ephemeris_used_for_local_time(
        data.date_of_birth,
        data.time_of_birth,
        data.timezone,
    )


def _project_chart_snapshot(chart: Any) -> dict[str, Any]:
    source = _record(chart)
    metadata = _record(source.get("metadata"))
    lagna = _record(source.get("lagna"))
    planets = _record(source.get("planets"))

    ayanamsha = metadata.get("ayanamsha")
    if ayanamsha != "Lahiri":
        raise _ProjectionError

    projected_planets = []
    for source_name, canonical_name in _PLANETS:
        planet = _record(planets.get(source_name))
        retrograde = planet.get("is_retrograde")
        if not isinstance(retrograde, bool):
            raise _ProjectionError
        projected_planets.append(
            {
                "name": canonical_name,
                "rashi": _canonical_name(planet.get("sign"), _RASHI_ALIASES),
                "degree": _finite_degree(planet.get("degree")),
                "house": _house(planet.get("house")),
                "retrograde": retrograde,
            }
        )

    projected_lagna = {
        "rashi": _canonical_name(lagna.get("sign"), _RASHI_ALIASES),
        "degree": _finite_degree(lagna.get("degree")),
    }
    _require_opposite_nodes(projected_planets)

    return {
        "ayanamsha": ayanamsha,
        "lagna": projected_lagna,
        "planets": projected_planets,
    }


def _project_chart(chart: Any, ephemeris: str) -> dict[str, Any]:
    source = _record(chart)
    planets = _record(source.get("planets"))
    moon = _record(planets.get("Moon"))
    snapshot = _project_chart_snapshot(chart)
    _require_whole_sign_houses(
        snapshot["lagna"]["rashi"],
        snapshot["planets"],
    )
    moon_facts = _project_moon_birth_facts(moon, snapshot["planets"][1])

    return {
        "contract_version": CONTRACT_VERSION,
        "engine": {
            "name": "DashaFlow",
            "version": _engine_version(),
            "ayanamsha": snapshot["ayanamsha"],
            "ephemeris": ephemeris,
        },
        "data": {
            **moon_facts,
            "lagna": snapshot["lagna"]["rashi"],
            "lagna_degree": snapshot["lagna"]["degree"],
            "planets": snapshot["planets"],
        },
    }


router = APIRouter()


@router.post(PROFILE_DERIVE_PATH, dependencies=[Depends(_require_api_token)])
def derive_profile(data: ProfileDeriveRequest) -> dict[str, Any]:
    try:
        chart = dashaflow.calculate_vedic_chart(
            data.date_of_birth,
            data.time_of_birth,
            data.latitude,
            data.longitude,
            data.timezone,
        )
        return _project_chart(chart, _ephemeris_used(data))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Profile derivation failed.",
        ) from None
