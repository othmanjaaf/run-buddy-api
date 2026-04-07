from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from app.auth.strava import get_authorization_url, exchange_code_for_token
from app.strava.client import get_athlete_profile, get_running_activities
from app.program.generator import generate_training_program
from app.models.schemas import ProgramRequest

app = FastAPI(title="Strava Running Program Generator")

import os

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8080,http://192.168.1.100:8080"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/auth/login")
def strava_login(frontend_origin: str = Query(default="http://localhost:8080")):
    url = get_authorization_url(frontend_origin=frontend_origin)
    return RedirectResponse(url)


@app.get("/auth/callback")
async def strava_callback(code: str = Query(...), state: str = Query(default="")):
    import urllib.parse
    token_data = await exchange_code_for_token(code)
    access_token = token_data["access_token"]
    frontend_origin = urllib.parse.unquote(state) if state else "http://localhost:8080"
    return RedirectResponse(f"{frontend_origin}/setup?token={access_token}")


@app.get("/athlete")
async def athlete_profile(access_token: str = Query(...)):
    profile = await get_athlete_profile(access_token)
    return profile


@app.get("/activities")
async def activities(access_token: str = Query(...)):
    runs = await get_running_activities(access_token)
    return runs


@app.post("/program")
async def generate_program(body: ProgramRequest):
    athlete = await get_athlete_profile(body.access_token)
    runs = await get_running_activities(body.access_token)
    plan = await generate_training_program(
        athlete=athlete,
        activities=runs,
        objective=body.objective,
        race_name=body.race_name,
        race_date=body.race_date,
        race_distance_km=body.race_distance_km,
        race_elevation_m=body.race_elevation_m,
        start_date=body.start_date,
        total_weeks=body.total_weeks,
        days_per_week=body.days_per_week,
        long_run_day=body.long_run_day,
        age=body.age,
        experience=body.experience,
        injury_history=body.injury_history,
        max_session_duration_min=body.max_session_duration_min,
        equipment=body.equipment,
    )
    return plan
