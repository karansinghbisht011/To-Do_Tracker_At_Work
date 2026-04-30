from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    database_url: str
    upstash_redis_rest_url: str = ""
    upstash_redis_rest_token: str = ""
    anthropic_api_key: str
    api_key: str
    cron_secret: str
    encryption_key: str
    base_url: str = "https://gen10x-todo-tracker.vercel.app"

    atlassian_client_id: str = ""
    atlassian_client_secret: str = ""
    atlassian_redirect_uri: str = ""

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""

    slack_client_id: str = ""
    slack_client_secret: str = ""
    slack_signing_secret: str = ""
    slack_redirect_uri: str = ""

    trello_api_key: str = ""
    trello_token: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
