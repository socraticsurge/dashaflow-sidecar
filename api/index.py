from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import date
import dashaflow

from api.election_chart import (
    ELECTION_CHART_DERIVE_PATH,
    router as election_chart_router,
)
from api.profile import PROFILE_DERIVE_PATH, router as profile_router
from api.contract_auth import require_api_token

app = FastAPI(title="DashaFlow Sidecar")

MAX_PRIVATE_CONTRACT_BODY_BYTES = 16 * 1024


class _PrivateContractBodyLimitMiddleware:
    """Bound private-contract request bodies before model validation."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") != "http"
            or not _is_private_contract_path(scope.get("path", ""))
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

        # Buffer only this deliberately small private-contract body, enforcing
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
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    _PrivateContractBodyLimitMiddleware,
    max_bytes=MAX_PRIVATE_CONTRACT_BODY_BYTES,
)

app.include_router(profile_router)
app.include_router(election_chart_router)


_PRIVATE_CONTRACT_PATHS = {
    PROFILE_DERIVE_PATH,
    ELECTION_CHART_DERIVE_PATH,
}


def _is_private_contract_path(path: str) -> bool:
    return path.rstrip("/") in _PRIVATE_CONTRACT_PATHS


@app.middleware("http")
async def protect_contract_responses(request: Request, call_next):
    private_path = _is_private_contract_path(request.url.path)
    if private_path:
        unavailable_detail = (
            "Profile derivation is not configured."
            if request.url.path.rstrip("/") == PROFILE_DERIVE_PATH
            else "Election chart derivation is not configured."
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
    if private_path:
        response.headers["Cache-Control"] = "private, no-store"
    return response


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    if _is_private_contract_path(request.url.path):
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})
    return await request_validation_exception_handler(request, exc)


class BirthData(BaseModel):
    date_of_birth: str   # YYYY-MM-DD
    time_of_birth: str   # HH:MM
    latitude: float
    longitude: float
    timezone: str = "UTC"


class TransitData(BaseModel):
    date_of_birth: str   # YYYY-MM-DD
    time_of_birth: str   # HH:MM
    latitude: float
    longitude: float
    timezone: str = "UTC"
    transit_date: str | None = None  # defaults to today


class CompatibilityData(BaseModel):
    p1: BirthData
    p2: BirthData


class MuhurthaData(BaseModel):
    birth_data: BirthData
    current_location_data: BirthData
    event_type: str = "General"
    start_date: str | None = None
    end_date: str | None = None


@app.get("/")
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "dashaflow-sidecar",
        "dashaflow_version": getattr(dashaflow, "__version__", "?"),
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/transit")
def transit(data: TransitData):
    """
    Overlay today's (or a given) transit chart on the natal chart.
    Returns planetary transits, Sade Sati status, Rahu-Ketu axis,
    and SAV transit points.
    """
    try:
        transit_date = data.transit_date or str(date.today())
        result = dashaflow.cast_transit(
            transit_date,
            data.date_of_birth,
            data.time_of_birth,
            data.latitude,
            data.longitude,
            data.timezone,
        )
        return {"status": "ok", "data": result, "transit_date": transit_date}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


from datetime import datetime, timedelta

@app.post("/compatibility")
def compatibility(data: CompatibilityData):
    """
    Ashtakoota Milan (36-point compatibility) between two profiles.
    """
    try:
        p1 = data.p1
        p2 = data.p2
        result = dashaflow.calculate_compatibility(
            p1.date_of_birth, p1.time_of_birth, p1.latitude, p1.longitude, p1.timezone,
            p2.date_of_birth, p2.time_of_birth, p2.latitude, p2.longitude, p2.timezone
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
            
        valid_activities = ['marriage', 'travel', 'business', 'education', 'house_entry', 'medical']
        if activity not in valid_activities:
            activity = "business"

        start_date = datetime.strptime(data.start_date or str(date.today()), "%Y-%m-%d")
        end_date = datetime.strptime(data.end_date or str(date.today()), "%Y-%m-%d")
        
        timings = []
        loc = data.current_location_data
        
        current_date = start_date
        while current_date <= end_date:
            d_str = current_date.strftime("%Y-%m-%d")
            res = dashaflow.check_muhurtha(
                activity, d_str, "10:00", loc.latitude, loc.longitude, loc.timezone
            )
            # Only include if there are more positive than negative factors, or if it's explicitly auspicious
            if res['total_positive'] > res['total_negative'] or res['verdict'] == 'auspicious':
                timings.append({
                    "date": d_str,
                    "start_time": "09:00",
                    "end_time": "12:00",
                    "points": res['positive_factors']
                })
            current_date += timedelta(days=1)
            
        return {"status": "ok", "data": {"timings": timings}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
