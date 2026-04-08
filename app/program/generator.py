import asyncio
import json
from datetime import datetime
from typing import List, Optional
import anthropic
from app.models.schemas import AthleteProfile, RunningActivity
from app.config import settings


def _format_activity_table(activities: List[RunningActivity]) -> str:
    if not activities:
        return "No recent running activities found."
    header = "| Date       | Distance (km) | Duration (min) | Avg Pace (min/km) | Avg HR |\n"
    header += "|------------|---------------|----------------|--------------------|---------|\n"
    rows = []
    for act in activities:
        dist_km = round(act.distance / 1000, 2)
        dur_min = round(act.moving_time / 60, 1)
        pace = (act.moving_time / 60) / (act.distance / 1000) if act.distance > 0 else 0
        pace_str = f"{int(pace)}:{int((pace % 1) * 60):02d}"
        hr = f"{int(act.average_heartrate)}" if act.average_heartrate else "N/A"
        rows.append(f"| {act.start_date[:10]} | {dist_km} | {dur_min} | {pace_str} | {hr} |")
    return header + "\n".join(rows)


def _compute_weekly_volume(activities: List[RunningActivity]) -> float:
    if not activities:
        return 0
    total_km = sum(a.distance / 1000 for a in activities)
    return round(total_km / max(len(activities) / 4, 1), 1)


# Map new session types to frontend types
TYPE_MAP = {
    "easy": "endurance",
    "long_run": "sortie-longue",
    "tempo": "fractionne",
    "intervals": "fractionne",
    "fartlek": "fractionne",
    "race_pace": "test",
    "rest": "repos",
    "strength": "renforcement",
    "renforcement": "renforcement",
    "endurance": "endurance",
    "fractionne": "fractionne",
    "sortie-longue": "sortie-longue",
    "test": "test",
}

VALID_TYPES = {"endurance", "fractionne", "repos", "renforcement", "sortie-longue", "test"}


def _convert_to_frontend(raw: dict, race_name: str, start_date: str) -> dict:
    athlete_info = raw.get("athlete", {})
    summary = raw.get("weekly_summary", {})
    coach_notes = raw.get("coach_notes", "")

    weeks = []
    for w in raw.get("plan", []):
        sessions = []
        for s in w.get("sessions", []):
            date_str = s.get("date", "")
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d")
                day_of_week = d.weekday()
            except Exception:
                day_of_week = 0

            raw_type = s.get("type", "easy").lower()
            frontend_type = TYPE_MAP.get(raw_type, "endurance")
            if frontend_type not in VALID_TYPES:
                frontend_type = "endurance"

            # Build rich description
            desc = s.get("description", "")
            intervals = s.get("intervals_detail")
            if intervals and intervals != "null":
                desc = f"{desc} — {intervals}"

            session = {
                "day": date_str,
                "dayOfWeek": day_of_week,
                "type": frontend_type,
                "description": desc,
            }
            if s.get("distance_km"):
                session["distance_km"] = s["distance_km"]
            if s.get("duration_min"):
                session["duration_min"] = s["duration_min"]
            if s.get("target_pace"):
                session["pace"] = s["target_pace"]

            sessions.append(session)

        phase = w.get("phase", "base").capitalize()
        total_km = w.get("total_km", 0)
        weeks.append({
            "weekNumber": w.get("week", 1),
            "theme": f"{phase} — {total_km} km",
            "sessions": sessions,
        })

    return {
        "raceName": athlete_info.get("race", race_name),
        "raceDate": athlete_info.get("race_date", ""),
        "totalWeeks": summary.get("total_weeks", len(weeks)),
        "startDate": start_date,
        "weeks": weeks,
        "coachNotes": coach_notes,
        "paceZones": raw.get("pace_zones", {}),
        "timelineAssessment": raw.get("timeline_assessment", {}),
    }


async def generate_training_program(
    athlete: AthleteProfile,
    activities: List[RunningActivity],
    objective: str,
    race_name: str,
    race_date: str,
    race_distance_km: float,
    race_elevation_m: int,
    start_date: str,
    total_weeks: int,
    days_per_week: int,
    long_run_day: str,
    age: Optional[int],
    experience: str,
    injury_history: str,
    max_session_duration_min: int,
    equipment: str,
) -> dict:
    activity_table = _format_activity_table(activities)
    weekly_volume = _compute_weekly_volume(activities)

    prompt = f"""You are an elite running coach with expertise in periodization and race preparation.
Generate a personalized training plan as a single valid JSON object. No commentary outside the JSON.

## Athlete Profile
- Name: {athlete.firstname} {athlete.lastname}
- Sex: {athlete.sex or 'N/A'}
- Age: {age or 'N/A'}
- Weight: {athlete.weight or 'N/A'} kg
- Current weekly volume: ~{weekly_volume} km/week
- Running experience: {experience}
- Injury history / constraints: {injury_history}
- Max session duration: {max_session_duration_min} min

## Recent Running Activities (last {len(activities)} sessions)
{activity_table}

## Goal
- Objective: {objective}
- Race name: {race_name}
- Race distance: {race_distance_km} km
- Race date: {race_date}
- Race elevation gain: {race_elevation_m} m

## Plan Parameters
- Plan start date: {start_date}
- Plan duration: {total_weeks} weeks
- Training days per week: {days_per_week}
- Preferred long run day: {long_run_day}
- Available equipment: {equipment}

## Session Types to Use
Use ONLY these session types:
- **easy**: recovery / base aerobic (conversational pace)
- **long_run**: weekly long run, progressive or steady
- **tempo**: sustained threshold effort (20-40 min at threshold)
- **intervals**: VO2max work (e.g. 5×1000m, 6×800m) with recovery jogs
- **fartlek**: unstructured speed play
- **race_pace**: blocks at goal race pace
- **rest**: no running

## Pace Zones (compute from recent activities)
Derive the following paces from the athlete's recent data. Output them in the JSON:
- easy_pace_min_per_km: ~60-75% effort
- long_run_pace_min_per_km
- tempo_pace_min_per_km
- interval_pace_min_per_km
- race_pace_min_per_km

## Periodization Rules
1. Progressive overload: increase total weekly volume by max +10% per week
2. Cutback week: every 3rd or 4th week, reduce volume by 30-40%
3. Taper: final 2 weeks → progressive volume reduction (60% → 40% of peak)
4. Long run cap: never exceed 35% of weekly volume in a single run
5. Hard/easy pattern: never schedule 2 hard sessions (tempo/intervals) on consecutive days
6. Race week: light shakeout runs only + race day
7. Specificity: increase race_pace sessions as race approaches

## Short Timeline Handling
| Available Weeks | Strategy |
|-----------------|----------|
| ≥ 10 | Full cycle: base → build → peak → taper |
| 6-9 | Compressed: skip base, start at build → peak → taper (1w) |
| 3-5 | Maintenance + sharpening: hold fitness, add 2-3 race-pace sessions, taper last week |
| 1-2 | Race-ready mode: easy volume only, shakeouts at race pace, full taper |

## Output JSON Schema
Return EXACTLY this structure:
{{
  "athlete": {{"name": "", "goal": "", "race": "", "race_date": "", "race_distance_km": 0}},
  "pace_zones": {{"easy": "X:XX", "long_run": "X:XX", "tempo": "X:XX", "interval": "X:XX", "race_pace": "X:XX"}},
  "plan": [
    {{
      "week": 1,
      "phase": "base | build | peak | taper",
      "total_km": 0,
      "sessions": [
        {{
          "day": "Monday",
          "date": "YYYY-MM-DD",
          "type": "easy | tempo | intervals | long_run | fartlek | race_pace | rest",
          "distance_km": 0,
          "target_pace": "X:XX",
          "duration_min": 0,
          "description": "Brief coaching instruction",
          "warmup_km": 0,
          "cooldown_km": 0,
          "intervals_detail": "5x1000m @ X:XX, 90s recovery or null"
        }}
      ]
    }}
  ],
  "weekly_summary": {{"total_weeks": 0, "peak_volume_km": 0, "taper_start_week": 0}},
  "coach_notes": "General advice, nutrition, recovery tips",
  "timeline_assessment": {{
    "available_weeks": 0,
    "tier": "full | compressed | maintenance | race_ready | race_week",
    "warning": "string or null",
    "rationale": "Brief explanation"
  }}
}}"""

    def _call_claude():
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, timeout=180.0)
        return client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

    loop = asyncio.get_event_loop()
    message = await loop.run_in_executor(None, _call_claude)
    raw_text = message.content[0].text.strip()

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    raw_text = raw_text.strip()

    raw = json.loads(raw_text)
    return _convert_to_frontend(raw, race_name, start_date)
