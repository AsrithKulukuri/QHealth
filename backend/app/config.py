from functools import lru_cache
from pathlib import Path
import urllib.parse
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DISCLAIMER = (
    "Research Prototype: This platform provides model-generated disease-risk predictions "
    "for research and decision-support purposes. Predictions are based on benchmark or "
    "user-provided datasets and are not a substitute for professional medical diagnosis, "
    "treatment, or clinical validation."
)

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="QHEALTH_", env_file=PROJECT_ROOT / ".env", extra="ignore")
    storage_root: Path = PROJECT_ROOT
    api_token: str = ""
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080"
    trusted_hosts: str = "localhost,127.0.0.1,backend,testserver"
    upload_limit_mb: int = Field(default=20, ge=1, le=100)
    max_rows: int = Field(default=100000, ge=20, le=1000000)
    max_columns: int = Field(default=200, ge=2, le=500)
    quantum_max_samples: int = Field(default=256, ge=20, le=1024)
    max_queued_jobs: int = Field(default=3, ge=1, le=10)
    log_level: str = "INFO"

    # Supabase & PostgreSQL production settings
    database_url: str = Field(default="", validation_alias=AliasChoices("QHEALTH_DATABASE_URL", "DATABASE_URL"))
    database_schema: str = Field(default="asrii", validation_alias=AliasChoices("QHEALTH_DATABASE_SCHEMA", "DATABASE_SCHEMA"))
    supabase_url: str = Field(default="", validation_alias=AliasChoices("QHEALTH_SUPABASE_URL", "SUPABASE_URL"))
    supabase_anon_key: str = Field(default="", validation_alias=AliasChoices("QHEALTH_SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY"))
    supabase_service_role_key: str = Field(default="", validation_alias=AliasChoices("QHEALTH_SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"))
    supabase_bucket: str = Field(default="qhealth-storage", validation_alias=AliasChoices("QHEALTH_SUPABASE_BUCKET", "SUPABASE_BUCKET"))

    @property
    def root(self) -> Path:
        return (PROJECT_ROOT / self.storage_root).resolve()

    @property
    def upload_limit(self) -> int:
        return self.upload_limit_mb * 1024 * 1024

    @property
    def is_postgres_enabled(self) -> bool:
        return bool(self.database_url)

    @property
    def is_supabase_storage_enabled(self) -> bool:
        return bool(self.supabase_url and (self.supabase_service_role_key or self.supabase_anon_key))

    @property
    def effective_schema(self) -> str:
        if self.database_url:
            parsed = urllib.parse.urlsplit(self.database_url)
            qs = urllib.parse.parse_qs(parsed.query)
            if "schema" in qs:
                return qs["schema"][0]
        return self.database_schema

    @property
    def normalized_database_url(self) -> str:
        if not self.database_url:
            return ""
        parsed = urllib.parse.urlsplit(self.database_url)
        scheme = parsed.scheme
        if scheme in ("postgresql", "postgres"):
            scheme = "postgresql+psycopg"
        # Filter query params to only standard PostgreSQL/libpq parameters
        qs = urllib.parse.parse_qs(parsed.query)
        allowed = {"sslmode", "connect_timeout", "application_name", "sslrootcert", "sslcert", "sslkey"}
        filtered_params = {k: v[0] for k, v in qs.items() if k.lower() in allowed}
        new_query = urllib.parse.urlencode(filtered_params)
        return urllib.parse.urlunsplit((scheme, parsed.netloc, parsed.path, new_query, parsed.fragment))

    def initialize_directories(self) -> None:
        for name in ["data/datasets", "models", "experiments"]:
            (self.root / name).mkdir(parents=True, exist_ok=True)

@lru_cache
def get_settings() -> Settings:
    return Settings()

