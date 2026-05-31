from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration object.

    Environment variable examples
    -----------------------------
    REDIS_URL=redis://localhost:6379/0
    MAX_BATCH_SIZE=500000
    CACHE_TTL_SECONDS=600
    LOG_LEVEL=DEBUG
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # Service metadata
    version: str = "1.0.0"
    log_level: str = "INFO"

    redis_url: str = "redis://localhost:6379/0"
    max_batch_size: int = 1_010_000
    cache_ttl_seconds: int = 300

    polars_streaming: bool = True

    kafka_bootstrap_servers: str = "localhost:9092"

    plaid_env: str = "local"
    plaid_client_id: str = ""
    plaid_secret: str = ""


settings = Settings()
