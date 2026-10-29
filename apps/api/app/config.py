from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://exambank:exambank_dev@localhost:5432/exambank"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    # Danh sách origin cách nhau dấu phẩy — khi public, thêm tên miền thật (VD: https://exambank.vercel.app)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    ai_api_key: str = ""
    ai_model: str = ""
    # EB-301: chọn nhà cung cấp AI bằng env, không sửa code khi đổi model
    ai_provider: str = "demo"  # demo | openai (OpenAI hoặc endpoint tương thích OpenAI)
    ai_base_url: str = "https://api.openai.com/v1"
    ai_async: bool = False  # True khi chạy cùng Celery worker + Redis (docker compose)

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
