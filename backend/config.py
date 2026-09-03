"""
LECTIO — Application Configuration
All settings loaded from environment / .env file via Pydantic BaseSettings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────
    app_name: str = "LECTIO"
    app_env: Literal["development", "production"] = "development"
    debug: bool = True
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────
    database_url: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "lectio_db"
    postgres_user: str = "lectio_user"
    postgres_password: str

    # ── ChromaDB ─────────────────────────────────────
    chroma_host: str = "chromadb"
    chroma_port: int = 8000
    chroma_auth_token: str

    # ── Security ─────────────────────────────────────
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── LLM — Groq (Free) ────────────────────────────
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    # ── LangSmith (Optional) ─────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "lectio-dev"

    # ── Embeddings ────────────────────────────────────
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_device: str = "cpu"

    # ── File Storage ──────────────────────────────────
    artifact_storage_path: str = "/app/uploads"
    max_upload_size_mb: int = 50

    # ── Auto-provisioned Admin (created on startup if missing) ─
    admin_email: str = "admin@lectio.ac.za"
    admin_password: str = "Admin@Lectio2025!"
    admin_full_name: str = "System Administrator"

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid:
            raise ValueError(f"log_level must be one of {valid}")
        return v.upper()

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings singleton.
    Use as FastAPI dependency: settings = Depends(get_settings)
    """
    return Settings()


# Convenient module-level access
settings = get_settings()
