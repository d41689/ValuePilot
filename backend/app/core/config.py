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
    # System-level "set start date and walk away" config (#40).
    # Format: "YYYY-QN" (e.g. "2024-Q1"). When set, on API boot the system
    # enqueues a quarterly_pipeline job for every quarter from this start
    # through the current calendar quarter that has no prior succeeded run.
    # Idempotent across restarts.
    THIRTEENF_START_QUARTER: Optional[str] = None
    EDGAR_REQUEST_DELAY_S: float = 0.1        # legacy fallback; 10 req/s default
    EDGAR_MAX_CONCURRENCY: int = 2
    EDGAR_MAX_RETRIES: int = 5
    EDGAR_RETRY_BACKOFF_S: str = "5,30,120,300,300"    # comma-separated seconds; parsed by _parse_backoff()
    EDGAR_FETCH_MODE: str = "live"            # live | replay
    # Rate Guard egress service. Required when EDGAR_FETCH_MODE=live (enforced
    # at startup) — EdgarClient routes every EDGAR fetch through it.
    RATE_GUARD_URL: Optional[str] = None
    # Persistent identity returned by Rate Guard's authenticated /v1/identity.
    # Live API startup fails unless the configured endpoint matches this value.
    RATE_GUARD_EXPECTED_INSTANCE_ID: Optional[str] = None
    # Development-only availability mode. It first probes RATE_GUARD_URL and
    # may use the private Compose fallback only when that origin is unreachable.
    # Production never enables this switch.
    RATE_GUARD_ALLOW_LOCAL_FALLBACK: bool = False
    RATE_GUARD_FALLBACK_URL: Optional[str] = None
    RATE_GUARD_PRIMARY_PROBE_INTERVAL_S: float = 30.0
    # Shared Bearer key for Rate Guard's public surface. When set, the client
    # sends `Authorization: Bearer <key>` on every fetch/metrics call and Rate
    # Guard rejects unauthenticated requests. Leave unset for internal-only
    # (auth disabled). The same value goes in the shared .env so the rate-guard
    # container and the api containers agree.
    RATE_GUARD_API_KEY: Optional[str] = None
    # Seed the curated manager universe on every API boot (M2). Off by default
    # so dev and test boots never write to institution_managers; prod turns it
    # on. A failure here is FATAL by design — an API with an empty or partial
    # manager universe ingests nothing and scores nothing, silently. See
    # app/services/manager_seed_startup.py.
    MANAGER_SEED_ON_STARTUP: bool = False     # prod: true
    # Apply the curated CUSIP override seed (seed_data/curated_cusip_overrides.json)
    # at the start of every full enrichment pass, so mega-caps OpenFIGI cannot map
    # (no US-composite listing — ExxonMobil, Honeywell) still link. Off by default
    # so dev/test enrichment never writes override mappings; prod turns it on at the
    # 13f-data-v1 data gate. Inert unless the enrichment pipeline runs at all, and
    # any un-applied override stays loud via the HIGH_IMPACT_CUSIP_UNRESOLVED
    # guardrail — so a forgotten flag can never fail silently.
    CUSIP_OVERRIDE_SEED_ENABLED: bool = False  # prod: true at data gate
    EDGAR_SCHEDULER_ENABLED: bool = False     # prod: true
    THIRTEENF_SMART_RETRY_ENABLED: bool = False
    THIRTEENF_JOB_WORKER_ENABLED: bool = False
    THIRTEENF_JOB_WORKER_POLL_INTERVAL_S: float = 2.0
    THIRTEENF_JOB_WORKER_HEARTBEAT_STALE_S: int = 90
    THIRTEENF_JOB_LEASE_SECONDS: int = 300
    DAILY_SYNC_EARLIEST_ATTEMPT_ET: str = "20:00"
    THIRTEENF_DAILY_SYNC_MAX_ATTEMPTS: int = 3
    # When daily sync has no watermark yet, materialize this many calendar days
    # ending today. Once a watermark exists, every later missing date is filled
    # regardless of outage length. This bounded first-run window avoids silently
    # assuming the scheduler was already running before the first status row.
    THIRTEENF_DAILY_SYNC_BOOTSTRAP_DAYS: int = 7
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

    # OpenFIGI
    OPENFIGI_API_KEY: Optional[str] = None

    # Raw document storage root
    EDGAR_RAW_STORAGE_DIR: str = "/code/storage/edgar_raw"

    # Market Data
    MARKET_DATA_PRIMARY: str = "none"
    MARKET_DATA_SECONDARY: str = "none"
    TWELVE_DATA_API_KEY: Optional[str] = None
    # Provider activation is an explicit authorization decision, not inferred
    # from a key that happens to exist in an inherited environment.
    MARKET_DATA_COMMERCIAL_ENABLED: bool = False
    # Yahoo's endpoint is development-only under the coverage source policy.
    MARKET_DATA_ALLOW_DEVELOPMENT_PROVIDER: bool = False

    # Initial Setup
    INITIAL_ADMIN_PASSWORD: Optional[str] = None

    # Notifications
    SLACK_WEBHOOK_URL: Optional[str] = None
    DISCORD_WEBHOOK_URL: Optional[str] = None
    BASE_URL: str = "http://localhost:3000"  # For links in notifications
    # Comma-separated current+previous Fernet keys: ``v2:<key>,v1:<key>``.
    # User destinations fail closed when this is absent or invalid.
    NOTIFICATION_SECRET_KEYS: Optional[str] = None
    NOTIFICATION_DELIVERY_ENABLED: bool = False
    # Materializes in-app research events even when EDGAR scheduling and
    # external delivery are disabled. Kept separate to avoid hidden coupling.
    RESEARCH_NOTIFICATION_SCHEDULER_ENABLED: bool = False
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: Optional[str] = None
    SMTP_TLS_REQUIRED: bool = True
    SMTP_TIMEOUT_SECONDS: float = 10.0

    # extra="ignore": docker-compose may inject deployment-only vars (e.g. VALUEPILOT_DB_*)
    # that are not declared in Settings; silently ignoring them avoids startup failures.
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
