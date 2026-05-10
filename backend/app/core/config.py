from typing import Optional, Any
from pydantic import Field, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "ValuePilot"
    API_V1_STR: str = "/api/v1"
    
    # Database
    POSTGRES_SERVER: str = "db"
    POSTGRES_USER: str = "user"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "valuepilot"
    
    # Storage
    UPLOAD_DIR: str = "/code/storage/uploads"
    
    # Prioritize DATABASE_URL from env, otherwise build it
    SQLALCHEMY_DATABASE_URI: Optional[str] = Field(None, validation_alias="DATABASE_URL")

    # JWT / Auth
    SECRET_KEY: str  # required; no default — startup fails if unset
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        
        # Fallback to building from components if not provided directly
        return str(f"postgresql://{info.data.get('POSTGRES_USER')}:{info.data.get('POSTGRES_PASSWORD')}@{info.data.get('POSTGRES_SERVER')}/{info.data.get('POSTGRES_DB')}")

    # EDGAR rate / retry
    SEC_CONTACT_EMAIL: Optional[str] = None
    EDGAR_REQUESTS_PER_SECOND: float = 10.0
    EDGAR_USER_AGENT: Optional[str] = None
    EDGAR_REQUEST_DELAY_S: float = 0.1        # legacy fallback; 10 req/s default
    EDGAR_MAX_CONCURRENCY: int = 2
    EDGAR_MAX_RETRIES: int = 5
    EDGAR_RETRY_BACKOFF_S: str = "5,30,120,300,300"    # comma-separated seconds; parsed by _parse_backoff()
    EDGAR_FETCH_MODE: str = "live"            # live | replay
    EDGAR_SCHEDULER_ENABLED: bool = False     # prod: true
    THIRTEENF_SMART_RETRY_ENABLED: bool = False
    THIRTEENF_JOB_WORKER_ENABLED: bool = False
    THIRTEENF_JOB_WORKER_POLL_INTERVAL_S: float = 2.0
    THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S: int = 90
    THIRTEENF_JOB_LEASE_SECONDS: int = 300
    DAILY_SYNC_EARLIEST_ATTEMPT_ET: str = "20:00"
    THIRTEENF_DAILY_SYNC_MAX_ATTEMPTS: int = 3
    THIRTEENF_WATCHDOG_INTERVAL_MINUTES: int = 15
    THIRTEENF_READY_LINK_RATIO: float = 0.80
    THIRTEENF_WARNING_LINK_RATIO: float = 0.50
    THIRTEENF_READY_HISTORICAL_DEPTH: int = 4
    THIRTEENF_MIN_HISTORICAL_DEPTH: int = 2
    EDGAR_RATE_LIMIT_WINDOW_S: int = 60

    # Dataroma rate / retry
    DATAROMA_REQUEST_DELAY_S: float = 2.0
    DATAROMA_MAX_RETRIES: int = 2
    DATAROMA_RETRY_BACKOFF_S: str = "10,60"    # comma-separated seconds; parsed by _parse_backoff()

    # Raw document storage root
    EDGAR_RAW_STORAGE_DIR: str = "/code/storage/edgar_raw"

    # Market Data
    MARKET_DATA_PRIMARY: str = "yfinance"
    MARKET_DATA_SECONDARY: str = "twelvedata"
    TWELVE_DATA_API_KEY: Optional[str] = None

    # Initial Setup
    INITIAL_ADMIN_PASSWORD: Optional[str] = None

    # Notifications
    SLACK_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None
    BASE_URL: str = "http://localhost:3000"  # For links in notifications

    # extra="ignore": docker-compose may inject deployment-only vars (e.g. VALUEPILOT_DB_*)
    # that are not declared in Settings; silently ignoring them avoids startup failures.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
