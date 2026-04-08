from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from app.auth.strava import get_authorization_url, exchange_code_for_token
from app.strava.client import get_athlete_profile, get_running_activities
from app.program.generator import generate_training_program
from app.models.schemas import ProgramRequest

app = FastAPI(title="Strava Running Program Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    import traceback
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "trace": traceback.format_exc()},
        headers={"Access-Control-Allow-Origin": "*"},
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


@app.get("/race-info")
async def race_info(url: str = Query(...)):
    import re
    import anthropic
    from app.config import settings

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    # Strip HTML tags for Claude
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:12000]

    prompt = f"""Extract race information from this webpage text and return ONLY a JSON object.

Webpage: {url}

Content:
{text}

Return this JSON structure (use null for missing fields):
{{
  "race_name": "string",
  "date": "YYYY-MM-DD or string",
  "start_time": "HH:MM or string",
  "location": "string",
  "distance_km": number,
  "elevation_m": number,
  "meeting_point": "string",
  "bag_drop": "string or null",
  "waves": ["Wave A: 8h00", ...] or null,
  "website": "string",
  "key_info": ["important note 1", "important note 2"]
}}"""

    def _call():
        c = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

    import asyncio
    loop = asyncio.get_event_loop()
    msg = await loop.run_in_executor(None, _call)
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    import json
    try:
        return json.loads(raw.strip())
    except Exception:
        return {"error": "Could not parse race info", "raw": raw}


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
