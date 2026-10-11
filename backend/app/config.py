from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """Runtime configuration, loaded from environment variables prefixed with ``PAYPLAN_``."""

    model_config = SettingsConfigDict(env_prefix="PAYPLAN_", env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://payplan:payplan@localhost:5432/payplan"
    # On AWS the URL is assembled from parts, because RDS keeps the password in a managed
    # Secrets Manager secret that ECS injects as its own environment variable.
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "payplan"
    db_user: str = "payplan"
    db_password: str | None = None
    db_sslmode: str | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 20

    cors_origins: list[str] = ["http://localhost:5173"]
    log_level: str = "INFO"
    # Emit CloudWatch Embedded Metric Format lines so ECS log shipping produces metrics.
    emf_enabled: bool = False
    metrics_namespace: str = "PayPlan"
    service_name: str = "payplan-api"

    # Sandbox gateway behaviour
    gateway_latency_ms: int = 150
    gateway_max_attempts: int = 3
    gateway_retry_base_delay_s: float = 0.2

    # An in-progress idempotency key older than this is considered abandoned and can be resumed.
    idempotency_lock_timeout_s: int = 30

    @model_validator(mode="after")
    def _assemble_database_url(self) -> "Settings":
        if self.db_host:
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.db_user,
                password=self.db_password,
                host=self.db_host,
                port=self.db_port,
                database=self.db_name,
                query={"sslmode": self.db_sslmode} if self.db_sslmode else {},
            ).render_as_string(hide_password=False)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
