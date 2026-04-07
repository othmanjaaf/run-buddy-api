from pydantic import BaseModel
from typing import Optional


class AthleteProfile(BaseModel):
    id: int
    firstname: str
    lastname: str
    city: Optional[str] = None
    country: Optional[str] = None
    sex: Optional[str] = None
    weight: Optional[float] = None  # kg


class RunningActivity(BaseModel):
    id: int
    name: str
    distance: float          # meters
    moving_time: int         # seconds
    elapsed_time: int        # seconds
    total_elevation_gain: float
    average_speed: float     # m/s
    max_speed: float         # m/s
    average_heartrate: Optional[float] = None
    max_heartrate: Optional[float] = None
    start_date: str
    type: str


class ProgramRequest(BaseModel):
    access_token: str
    objective: str
    race_name: str = "Ma course"
    race_date: str
    race_distance_km: float = 10.0
    race_elevation_m: int = 0
    start_date: str
    total_weeks: int = 8
    days_per_week: int = 4
    long_run_day: str = "Sunday"
    age: Optional[int] = None
    experience: str = "intermediate"   # beginner | intermediate | advanced
    injury_history: str = "none"
    max_session_duration_min: int = 90
    equipment: str = "none"            # treadmill, track, hills, none
