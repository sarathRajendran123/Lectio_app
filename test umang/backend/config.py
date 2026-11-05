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
    generation_auto_enabled: bool = True   # draft fixes for the worst gaps after an audit (capped; the lecturer can also request more)
    generation_max_items_per_run: int = 4  # free-tier friendly: most severe gaps, one per gap type first
    paperclip_api_url: str = ""
    paperclip_api_key: str = ""
    paperclip_company_id: str = ""
    paperclip_agent_id: str = ""
    parser_timeout_seconds: int = 60
    workflow_timeout_seconds: int = 600
    max_concurrent_runs: int = 2
    llm_timeout_seconds: int = 90
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

    # ── LLM — OpenRouter (OpenAI-compatible; free-tier model by default) ─────
    # Free models are rate-limited and can be withdrawn: verify availability
    # (GET https://openrouter.ai/api/v1/models) and override via env if needed.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "nvidia/nemotron-3.5-super-vl:free"
    openrouter_fallback_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"  # one bounded retry, "" disables
    openrouter_model_variants: list[str] = []
    llm_max_tokens_audit: int = 6000   # reasoning models spend part of this on thinking
    llm_max_tokens_generation: int = 3000
    llm_retry_wait_seconds: float = 6.0  # one pause + second pass when every model is rate-limited
    llm_reasoning_effort: str = "low"   # limits hidden thinking tokens on reasoning models ("" disables)
    llm_cache_enabled: bool = True   # identical validated requests are reused, not re-billed

    # ── LangSmith (Optional) ─────────────────────────
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False
    langchain_project: str = "lectio-dev"

    # ── Embeddings ────────────────────────────────────
    # Multilingual (German + English); 1024-d. Changing it invalidates stored vectors.
    embedding_model: str = "BAAI/bge-m3"
    rerank_model: str = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
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
    def llm_ready(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def llm_models(self) -> list[str]:
        return list(dict.fromkeys([self.openrouter_model, *self.openrouter_model_variants]))

    @property
    def llm_cache_dir(self) -> str:
        return self.artifact_storage_path.rstrip("/\\") + "/.llm_cache"

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
