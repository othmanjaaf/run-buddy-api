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
    import json
    import anthropic
    from urllib.parse import urljoin
    from app.config import settings

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            html = resp.text
            base_url = str(resp.url)
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": str(e)})

    # Extract image URLs that look like course maps
    img_urls = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    course_keywords = ["parcours", "course", "map", "trace", "itinera", "plan", "circuit", "elevation", "profil"]
    course_images = []
    for img in img_urls:
        if any(kw in img.lower() for kw in course_keywords):
            full_url = urljoin(base_url, img)
            course_images.append(full_url)
    # Also check alt text and surrounding context
    img_with_alt = re.findall(r'<img[^>]+alt=["\']([^"\']*parcours[^"\']*)["\'][^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    img_with_alt += re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]+alt=["\']([^"\']*parcours[^"\']*)["\']', html, re.IGNORECASE)
    for match in img_with_alt:
        src = match[1] if len(match) > 1 else match[0]
        full_url = urljoin(base_url, src)
        if full_url not in course_images:
            course_images.append(full_url)

    # Strip HTML for Claude
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:14000]

    prompt = f"""You are analyzing a race/running event webpage. Extract all information and return ONLY a valid JSON object.

Webpage URL: {url}
Page content:
{text}

Return EXACTLY this JSON (null for missing fields):
{{
  "race_name": "string",
  "date": "string",
  "start_time": "string",
  "location": "string",
  "distance_km": number or null,
  "elevation_m": number or null,
  "meeting_point": "string or null",
  "bag_drop": "string or null",
  "waves": ["Wave A: 8h00", "Wave B: 8h30"] or null,
  "key_info": ["max 5 important notes for runners"],
  "course_description": "2-3 sentences describing the course profile, terrain, key segments",
  "nutrition_points": ["km X: ravitaillement eau", "km Y: gel disponible"] or null,
  "checklist_j7": [
    "Récupérer son dossard à [lieu si mentionné]",
    "Préparer sa tenue et équipement",
    "Réduire l'intensité des entraînements",
    "Vérifier les transports / parking",
    "Confirmer l'heure de départ et le point de rendez-vous"
  ],
  "checklist_j1": [
    "Préparer son sac : dossard, chaussures, tenue, gels",
    "Hydratation : boire 2-3L dans la journée",
    "Dîner glucidique léger (pâtes, riz)",
    "Coucher tôt, réveil planifié",
    "Vérifier la météo du lendemain",
    "Déposer les bagages si bag drop disponible"
  ],
  "checklist_jour_j": [
    "Réveil 3h avant le départ",
    "Petit-déjeuner connu et testé à l'entraînement",
    "Épingler le dossard",
    "Arriver 45 min avant le départ",
    "Échauffement 15 min avant le départ",
    "Crème anti-frottement sur les zones sensibles",
    "Prendre un gel 15 min avant le départ"
  ],
  "race_plan_segments": [
    {{
      "segment": "0 - X km",
      "strategy": "Partir en douceur, 10-15 sec plus lent que l'allure cible",
      "tip": "Ne pas se laisser emporter par l'euphorie du départ"
    }}
  ]
}}

For race_plan_segments: create 4-6 meaningful segments based on the actual course (climbs, flat, descents, finish). Each segment should have concrete tactical advice."""

    def _call():
        c = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        return c.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
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
    try:
        result = json.loads(raw.strip())
        result["course_images"] = course_images[:3]  # max 3 images
        return result
    except Exception:
        return {"error": "Could not parse race info", "course_images": course_images[:3]}


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
