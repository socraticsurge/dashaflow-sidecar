import os
import re
from datetime import UTC, date, datetime, timedelta

import dashaflow
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from api.contract_auth import require_api_token
from api.election_chart import (
    ELECTION_CHART_DERIVE_PATH,
)
from api.election_chart import (
    router as election_chart_router,
)
from api.profile import PROFILE_DERIVE_PATH
from api.profile import router as profile_router

SOURCE_REPOSITORY_URL = "https://github.com/socraticsurge/dashaflow-sidecar"
LICENSE_SPDX = "AGPL-3.0-or-later"
_SOURCE_REVISION_PATTERN = re.compile(r"[0-9a-fA-F]{40}\Z")


def _source_revision() -> str | None:
    """Return only a Git commit identifier that can safely enter a URL."""

    for variable in ("SOURCE_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA"):
        value = os.environ.get(variable, "").strip()
        if _SOURCE_REVISION_PATTERN.fullmatch(value):
            return value.lower()
    return None


def _source_offer() -> dict[str, object]:
    revision = _source_revision()
    source_url = (
        f"{SOURCE_REPOSITORY_URL}/tree/{revision}"
        if revision
        else SOURCE_REPOSITORY_URL
    )
    license_ref = revision or "master"
    return {
        "license": {
            "spdx": LICENSE_SPDX,
            "url": f"{SOURCE_REPOSITORY_URL}/blob/{license_ref}/LICENSE",
        },
        "source": {
            "repository": SOURCE_REPOSITORY_URL,
            "revision": revision,
            "url": source_url,
        },
    }


app = FastAPI(
    title="DashaFlow Sidecar",
    description=(
        "AstroChaganti calculation sidecar. Complete corresponding source is "
        f"available at {SOURCE_REPOSITORY_URL}."
    ),
    license_info={
        "name": "GNU Affero General Public License v3.0 or later",
        "identifier": LICENSE_SPDX,
    },
)

MAX_CALCULATION_BODY_BYTES = 16 * 1024
MAX_MUHURTHA_DAYS = 31

_LEGACY_CALCULATION_PATHS = {
    "/calculate",
    "/transit",
    "/career",
    "/compatibility",
    "/muhurtha",
}
_CALCULATION_PATHS = {
    PROFILE_DERIVE_PATH,
    ELECTION_CHART_DERIVE_PATH,
    *_LEGACY_CALCULATION_PATHS,
}


def _is_calculation_path(path: str) -> bool:
    return path.rstrip("/") in _CALCULATION_PATHS


class _CalculationBodyLimitMiddleware:
    """Bound every calculation body before JSON parsing and validation."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") != "http"
            or not _is_calculation_path(scope.get("path", ""))
            or scope.get("method") != "POST"
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content={"detail": "Request body is too large."},
                    headers={"Cache-Control": "private, no-store"},
                )(scope, receive, send)
                return

        # Buffer only this deliberately small calculation body, enforcing
        # the byte ceiling before Starlette/FastAPI starts JSON parsing. Raising
        # from a wrapped receive callable is translated by the parser into its
        # own 400 response, so pre-reading is required for a stable sanitized
        # 413 on chunked requests without Content-Length.
        received = 0
        buffered_messages = []
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    await JSONResponse(
                        status_code=413,
                        content={"detail": "Request body is too large."},
                        headers={"Cache-Control": "private, no-store"},
                    )(scope, receive, send)
                    return
                if message.get("more_body", False):
                    continue
            break

        buffered_index = 0

        async def replay_receive():
            nonlocal buffered_index
            if buffered_index < len(buffered_messages):
                message = buffered_messages[buffered_index]
                buffered_index += 1
                return message
            return await receive()

        await self.app(scope, replay_receive, send)


app.add_middleware(
    _CalculationBodyLimitMiddleware,
    max_bytes=MAX_CALCULATION_BODY_BYTES,
)

app.include_router(profile_router)
app.include_router(election_chart_router)


@app.middleware("http")
async def protect_contract_responses(request: Request, call_next):
    calculation_path = _is_calculation_path(request.url.path)
    if calculation_path:
        unavailable_detail = (
            "Profile derivation is not configured."
            if request.url.path.rstrip("/") == PROFILE_DERIVE_PATH
            else (
                "Election chart derivation is not configured."
                if request.url.path.rstrip("/") == ELECTION_CHART_DERIVE_PATH
                else "Calculation service is not configured."
            )
        )
        try:
            # Enforce authentication before FastAPI reads or validates the
            # request body. Endpoint dependencies remain as defense in depth.
            require_api_token(
                request.headers.get("Authorization"),
                unavailable_detail=unavailable_detail,
            )
        except HTTPException as exc:
            headers = {
                **(exc.headers or {}),
                "Cache-Control": "private, no-store",
            }
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=headers,
            )
    response = await call_next(request)
    if calculation_path:
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    del request, exc
    return JSONResponse(status_code=422, content={"detail": "Invalid request."})


class BirthData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_of_birth: str = Field(min_length=10, max_length=10)  # YYYY-MM-DD
    time_of_birth: str = Field(min_length=5, max_length=8)  # HH:MM or HH:MM:SS
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class TransitData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date_of_birth: str = Field(min_length=10, max_length=10)  # YYYY-MM-DD
    time_of_birth: str = Field(min_length=5, max_length=8)  # HH:MM or HH:MM:SS
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    transit_date: str | None = Field(default=None, min_length=10, max_length=10)


class CompatibilityData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p1: BirthData
    p2: BirthData


class MuhurthaData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Retained as an optional compatibility field. DashaFlow's Muhurtha
    # calculation depends only on the event location and date window.
    birth_data: BirthData | None = None
    current_location_data: BirthData
    event_type: str = Field(default="General", min_length=1, max_length=64)
    start_date: str | None = Field(default=None, min_length=10, max_length=10)
    end_date: str | None = Field(default=None, min_length=10, max_length=10)


@app.get("/")
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dashaflow-sidecar",
        "dashaflow_version": getattr(dashaflow, "__version__", "?"),
        **_source_offer(),
    }


@app.post("/calculate")
def calculate(data: BirthData):
    try:
        chart = dashaflow.calculate_vedic_chart(
            data.date_of_birth,
            data.time_of_birth,
            data.latitude,
            data.longitude,
            data.timezone,
        )
        return {"status": "ok", "data": chart}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Calculation failed.") from exc


@app.post("/transit")
def transit(data: TransitData):
    """
    Overlay today's (or a given) transit chart on the natal chart.
    Returns planetary transits, Sade Sati status, Rahu-Ketu axis,
    and SAV transit points.
    """
    try:
        transit_date = data.transit_date or str(datetime.now(UTC).date())
        result = dashaflow.cast_transit(
            transit_date,
            data.date_of_birth,
            data.time_of_birth,
            data.latitude,
            data.longitude,
            data.timezone,
        )
        return {"status": "ok", "data": result, "transit_date": transit_date}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Calculation failed.") from exc


@app.post("/career")
def career(data: BirthData):
    """
    D10 Dashamsha career analysis. Returns career themes, planet-domain
    significations, and recommendations based on the 10th divisional chart.
    """
    try:
        result = dashaflow.analyze_career(
            data.date_of_birth,
            data.time_of_birth,
            data.latitude,
            data.longitude,
            data.timezone,
        )
        return {"status": "ok", "data": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Calculation failed.") from exc


@app.post("/compatibility")
def compatibility(data: CompatibilityData):
    """
    Ashtakoota Milan (36-point compatibility) between two profiles.
    """
    try:
        p1 = data.p1
        p2 = data.p2
        result = dashaflow.calculate_compatibility(
            p1.date_of_birth,
            p1.time_of_birth,
            p1.latitude,
            p1.longitude,
            p1.timezone,
            p2.date_of_birth,
            p2.time_of_birth,
            p2.latitude,
            p2.longitude,
            p2.timezone,
        )
        return {"status": "ok", "data": result}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Calculation failed.") from exc


@app.post("/muhurtha")
def muhurtha(data: MuhurthaData):
    """
    Check auspicious timings (Muhurtha) for a given event and date window.
    """
    try:
        activity = data.event_type.lower()
        if activity == "house warming":
            activity = "house_entry"
        elif activity == "vehicle purchase":
            activity = "travel"
        elif activity == "general" or activity == "property":
            activity = "business"

        valid_activities = [
            "marriage",
            "travel",
            "business",
            "education",
            "house_entry",
            "medical",
        ]
        if activity not in valid_activities:
            activity = "business"

        today = datetime.now(UTC).date()
        start_date = date.fromisoformat(data.start_date or str(today))
        end_date = date.fromisoformat(data.end_date or str(today))
        if end_date < start_date:
            raise HTTPException(
                status_code=422,
                detail="Invalid Muhurtha date window.",
            )
        inclusive_days = (end_date - start_date).days + 1
        if inclusive_days > MAX_MUHURTHA_DAYS:
            raise HTTPException(
                status_code=422,
                detail=f"Muhurtha date window cannot exceed {MAX_MUHURTHA_DAYS} days.",
            )

        timings = []
        loc = data.current_location_data

        current_date = start_date
        while current_date <= end_date:
            d_str = current_date.strftime("%Y-%m-%d")
            res = dashaflow.check_muhurtha(
                activity, d_str, "10:00", loc.latitude, loc.longitude, loc.timezone
            )
            # Only include if there are more positive than negative factors, or if it's explicitly auspicious
            if (
                res["total_positive"] > res["total_negative"]
                or res["verdict"] == "auspicious"
            ):
                timings.append(
                    {
                        "date": d_str,
                        "start_time": "09:00",
                        "end_time": "12:00",
                        "points": res["positive_factors"],
                    }
                )
            current_date += timedelta(days=1)

        return {"status": "ok", "data": {"timings": timings}}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Invalid Muhurtha date window.",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Calculation failed.") from exc
