from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date
import dashaflow

app = FastAPI(title="DashaFlow Sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.post("/compatibility")
def compatibility(data: CompatibilityData):
    """
    Ashtakoota Milan (36-point compatibility) between two profiles.
    """
    try:
        result = dashaflow.calculate_compatibility(
            data.p1.model_dump(),
            data.p2.model_dump()
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
        result = dashaflow.check_muhurtha(
            data.birth_data.model_dump(),
            data.current_location_data.model_dump(),
            data.event_type,
            data.start_date,
            data.end_date
        )
        return {"status": "ok", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
