"""Authenticated, bounded election-chart projection for trusted callers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import dashaflow
import pytz
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
from api.profile import (
    _RASHI_NAMES,
    _engine_version,
    _ephemeris_used_for_local_time,
    _project_chart_snapshot,
)

ELECTION_CHART_DERIVE_PATH = "/v1/election-chart/derive"
CONTRACT_VERSION = "1.0"
MAX_INSTANTS = 24
PAST_WINDOW = timedelta(days=366)
FUTURE_WINDOW = timedelta(days=1830)

# The engine's public primitive accepts HH:MM. Seconds and fractions therefore
# must be zero rather than being accepted and silently truncated.
_INSTANT_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:00"
    r"(?:\.0{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)\Z"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_instant(value: str) -> datetime:
    if len(value) > 32 or not _INSTANT_PATTERN.fullmatch(value):
        raise ValueError("instant must be a minute-precision RFC3339 timestamp")

    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("instant must be a real timestamp") from exc

    offset = parsed.utcoffset()
    if offset is None or abs(offset.total_seconds()) > 14 * 60 * 60:
        raise ValueError("instant must use a valid UTC offset")
    return parsed.astimezone(timezone.utc)


class ElectionLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: StrictStr = Field(min_length=1, max_length=64)

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


class ElectionChartDeriveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    contract_version: Literal[CONTRACT_VERSION]
    location: ElectionLocation
    instants: list[StrictStr] = Field(min_length=1, max_length=MAX_INSTANTS)

    @model_validator(mode="after")
    def validate_instants(self) -> ElectionChartDeriveRequest:
        now = _utc_now()
        earliest = now - PAST_WINDOW
        latest = now + FUTURE_WINDOW
        seen: set[datetime] = set()

        for value in self.instants:
            instant = _parse_instant(value)
            if instant < earliest or instant > latest:
                raise ValueError("instant is outside the supported event window")
            if instant in seen:
                raise ValueError("instants must identify unique moments")
            seen.add(instant)
        return self


def _require_api_token(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    require_api_token(
        authorization,
        unavailable_detail="Election chart derivation is not configured.",
    )


def _whole_sign_house(rashi: str, lagna_rashi: str) -> int:
    return (_RASHI_NAMES.index(rashi) - _RASHI_NAMES.index(lagna_rashi)) % 12 + 1


def _project_whole_sign_snapshot(chart: Any, instant: str) -> dict[str, Any]:
    projected = _project_chart_snapshot(chart)
    lagna = projected["lagna"]
    planets = []
    for planet in projected["planets"]:
        planets.append(
            {
                **planet,
                "house": _whole_sign_house(planet["rashi"], lagna["rashi"]),
            }
        )
    return {
        "instant": instant,
        "lagna": lagna,
        "planets": planets,
    }


def _aggregate_ephemeris(values: list[str]) -> str:
    unique = set(values)
    return values[0] if len(unique) == 1 else "mixed"


router = APIRouter()


@router.post(
    ELECTION_CHART_DERIVE_PATH,
    dependencies=[Depends(_require_api_token)],
)
def derive_election_charts(data: ElectionChartDeriveRequest) -> dict[str, Any]:
    try:
        local_timezone = pytz.timezone(data.location.timezone)
        snapshots = []
        ephemerides = []

        for requested_instant in data.instants:
            local_instant = _parse_instant(requested_instant).astimezone(local_timezone)
            local_date = local_instant.date().isoformat()
            local_time = local_instant.strftime("%H:%M")
            chart = dashaflow.calculate_vedic_chart(
                local_date,
                local_time,
                data.location.latitude,
                data.location.longitude,
                data.location.timezone,
            )
            snapshots.append(_project_whole_sign_snapshot(chart, requested_instant))
            ephemerides.append(
                _ephemeris_used_for_local_time(
                    local_date,
                    local_time,
                    data.location.timezone,
                )
            )

        return {
            "contract_version": CONTRACT_VERSION,
            "engine": {
                "name": "DashaFlow",
                "version": _engine_version(),
                "ayanamsha": "Lahiri",
                "ephemeris": _aggregate_ephemeris(ephemerides),
            },
            "house_system": "whole_sign",
            "location": {
                "latitude": data.location.latitude,
                "longitude": data.location.longitude,
                "timezone": data.location.timezone,
            },
            "data": {"charts": snapshots},
        }
    # This is the external engine boundary. Its exception types are not part of
    # the DashaFlow API, so every failure is deliberately collapsed to one safe
    # response without logging the potentially sensitive exception text.
    except Exception:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Election chart derivation failed.",
        ) from None
