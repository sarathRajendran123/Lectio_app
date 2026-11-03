"""
LECTIO — Application Configuration
All settings loaded from environment / .env file via Pydantic BaseSettings.
"""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
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
    debug: bool = False
    runtime_mode: Literal["live", "local_test"] = "live"
    retrieval_backend: Literal["neural", "lexical"] = "neural"
    generation_auto_enabled: bool = True
    paperclip_api_url: str = ""
    paperclip_api_key: str = ""
    paperclip_company_id: str = ""
    paperclip_agent_id: str = ""
    parser_timeout_seconds: int = 60
    workflow_timeout_seconds: int = 600
    max_concurrent_runs: int = 2
    llm_timeout_seconds: int = 45
    paperclip_enabled: bool = False
    log_level: str = "INFO"

    # ── Database ─────────────────────────────────────
    database_url: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "lectio_db"
    postgres_user: str = "lectio_user"
    postgres_password: str = ""

    # Dense vectors are stored transactionally with course chunks.

    # ── Security ─────────────────────────────────────
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # ── LLM — Groq (Free) ────────────────────────────
    groq_api_key: str = ""
    # llama-3.3-70b-versatile was decommissioned by Groq on 2026-08-16 (announced
    # 2026-06-17) -- every call using it now fails with a "model_decommissioned"
    # error. openai/gpt-oss-120b is Groq's official recommended replacement.
    # Overridable via GROQ_MODEL env var so future Groq deprecations don't
    # require a code change again.
    groq_model_variants: list[str] = []
    groq_model: str = "openai/gpt-oss-120b"

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
    admin_password: str = ""
    admin_full_name: str = "System Administrator"

    @model_validator(mode="after")
    def secure_configuration(self):
        if any(marker in self.secret_key.lower() for marker in ("replace_with", "change_me", "changeme", "your-secret")):
            raise ValueError("SECRET_KEY is still a placeholder; generate a fresh random secret")
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters")
        if self.app_env == "production" and (self.runtime_mode != "live" or self.debug):
            raise ValueError("Production requires live mode and DEBUG=false")
        return self

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
