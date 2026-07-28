from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import date, datetime, timedelta
import dashaflow
import pytz
import swisseph as swe
from dashaflow.constants import (
    DASHA_SEQUENCE,
    NAK_SPAN,
    VIMSHOTTARI_YEARS,
)
from dashaflow.dasha import _build_sub_periods
from dashaflow.nakshatra import get_nakshatra

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
    query_date: str | None = None


class DashaSubperiodData(BirthData):
    path: list[int]


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
            data.query_date,
        )
        return {"status": "ok", "data": chart}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _dasha_roots(data: BirthData):
    """Rebuild DashaFlow's exact major-period inputs for lazy drill-down."""
    local_tz = pytz.timezone(data.timezone)
    naive_dt = datetime.strptime(
        f"{data.date_of_birth} {data.time_of_birth}",
        "%Y-%m-%d %H:%M",
    )
    local_dt = local_tz.localize(naive_dt)
    utc_dt = local_dt.astimezone(pytz.utc)
    hour = utc_dt.hour + utc_dt.minute / 60.0 + utc_dt.second / 3600.0

    swe.set_ephe_path("")
    swe.set_sid_mode(swe.SIDM_LAHIRI)
    jd = swe.julday(utc_dt.year, utc_dt.month, utc_dt.day, hour)
    moon_result, _ = swe.calc_ut(
        jd,
        swe.MOON,
        swe.FLG_SIDEREAL | swe.FLG_SPEED,
    )
    moon_longitude = moon_result[0]
    nak_info = get_nakshatra(moon_longitude)
    nak_lord = nak_info["lord"]
    remaining_fraction = 1.0 - (
        nak_info["degree_in_nakshatra"] / NAK_SPAN
    )
    sequence_start = DASHA_SEQUENCE.index(nak_lord)

    birth_dt = local_dt.replace(tzinfo=None)
    roots = []
    cursor = birth_dt
    first_days = VIMSHOTTARI_YEARS[nak_lord] * remaining_fraction * 365.2425
    first_end = cursor + timedelta(days=first_days)
    roots.append(
        {
            "planet": nak_lord,
            "start": cursor.strftime("%Y-%m-%d"),
            "end": first_end.strftime("%Y-%m-%d"),
            "days": round(first_days, 2),
        }
    )
    cursor = first_end

    # Mirror DashaFlow 1.1.0's two-cycle major timeline, then trim at 120 years.
    for cycle in range(2):
        start_offset = 1 if cycle == 0 else 0
        for index in range(start_offset, 9):
            lord = DASHA_SEQUENCE[(sequence_start + index) % 9]
            days = VIMSHOTTARI_YEARS[lord] * 365.2425
            end = cursor + timedelta(days=days)
            roots.append(
                {
                    "planet": lord,
                    "start": cursor.strftime("%Y-%m-%d"),
                    "end": end.strftime("%Y-%m-%d"),
                    "days": days,
                }
            )
            cursor = end

    cutoff = birth_dt + timedelta(days=120 * 365.2425)
    compact = []
    for period in roots:
        compact.append(period)
        if datetime.strptime(period["end"], "%Y-%m-%d") > cutoff:
            break
    return compact


def _children_for_path(data: DashaSubperiodData):
    if not 1 <= len(data.path) <= 4:
        raise ValueError("path must contain between 1 and 4 period indexes")
    if any(index < 0 or index > 8 for index in data.path):
        raise ValueError("each path index must be between 0 and 8")

    roots = _dasha_roots(data)
    if data.path[0] >= len(roots):
        raise ValueError("root period index is outside the chart timeline")

    parent = roots[data.path[0]]
    for index in data.path[1:]:
        candidates = _build_sub_periods(
            datetime.strptime(parent["start"], "%Y-%m-%d"),
            parent["days"],
            parent["planet"],
        )
        parent = candidates[index]

    children = _build_sub_periods(
        datetime.strptime(parent["start"], "%Y-%m-%d"),
        parent["days"],
        parent["planet"],
    )
    return parent, children


@app.post("/dasha-subperiods")
def dasha_subperiods(data: DashaSubperiodData):
    """
    Return one lazy accordion level using DashaFlow's exact period builder.

    A path of [2] returns the nine Antardashas for Mahadasha index 2.
    [2, 4] returns the nine Pratyantardashas for its fifth Antardasha.
    The maximum path length is four, whose children are Prana periods.
    """
    try:
        parent, children = _children_for_path(data)
        return {
            "status": "ok",
            "data": {
                "path": data.path,
                "parent": parent,
                "children": children,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
