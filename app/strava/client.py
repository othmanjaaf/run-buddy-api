import httpx
from fastapi import HTTPException
from typing import List
from app.models.schemas import AthleteProfile, RunningActivity


STRAVA_API_BASE = "https://www.strava.com/api/v3"


async def get_athlete_profile(access_token: str) -> AthleteProfile:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{STRAVA_API_BASE}/athlete",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired Strava access token")
    data = response.json()
    return AthleteProfile(
        id=data["id"],
        firstname=data["firstname"],
        lastname=data["lastname"],
        city=data.get("city"),
        country=data.get("country"),
        sex=data.get("sex"),
        weight=data.get("weight"),
    )


async def get_running_activities(access_token: str, per_page: int = 30) -> List[RunningActivity]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{STRAVA_API_BASE}/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": per_page, "page": 1},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to fetch activities")

    RUNNING_TYPES = {"Run", "TrailRun", "VirtualRun"}

    activities = []
    for act in response.json():
        activity_type = act.get("sport_type") or act.get("type", "")
        if activity_type not in RUNNING_TYPES:
            continue
        if act.get("distance", 0) <= 0:
            continue
        activities.append(
            RunningActivity(
                id=act["id"],
                name=act["name"],
                distance=act["distance"],
                moving_time=act["moving_time"],
                elapsed_time=act["elapsed_time"],
                total_elevation_gain=act["total_elevation_gain"],
                average_speed=act["average_speed"],
                max_speed=act["max_speed"],
                average_heartrate=act.get("average_heartrate"),
                max_heartrate=act.get("max_heartrate"),
                start_date=act["start_date"],
                type=activity_type,
            )
        )
    return activities
