from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    s3_bucket: str = "local-upload-test"
    s3_region: str = "us-east-1"
    s3_access_key: str
    s3_secret_key: str
    s3_public_endpoint: str

    upload_prefix: str = "uploads"
    api_base_url: str = ""
    max_upload_bytes: int = 10 * 1024 * 1024
    allowed_content_types: list[str] = ["image/jpeg", "image/png"]

    create_bucket: bool = True
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
