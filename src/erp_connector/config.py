from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    database_url: str = "postgresql+psycopg://localhost/erp_demo"
    api_key: SecretStr = Field(min_length=32)
    erp_api_key: SecretStr = Field(min_length=32)
    erp_base_url: str = "http://127.0.0.1:8110"
    source_db_path: str = "./erp-demo.db"
    page_size: int = Field(default=2, ge=1, le=100)
    max_pages: int = Field(default=10, ge=1, le=50)
    retry_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("erp_base_url")
    @classmethod
    def fixed_http_origin(cls, value):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("ERP_BASE_URL must be a fixed HTTP(S) origin without credentials")
        return value.rstrip("/")
