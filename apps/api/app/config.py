from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://exambank:exambank_dev@localhost:5432/exambank"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    ai_api_key: str = ""
    ai_model: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
