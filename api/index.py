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
