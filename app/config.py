from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    strava_client_id: str
    strava_client_secret: str
    strava_redirect_uri: str = "http://localhost:8000/auth/callback"
    anthropic_api_key: str

    class Config:
        env_file = ".env"


settings = Settings()
