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
    SECRET_KEY: str = "change-me-in-production-use-a-long-random-string"
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
    EDGAR_USER_AGENT: str = "ValuePilot contact@valuepilot.com"
    EDGAR_REQUEST_DELAY_S: float = 0.2        # 5 req/s; prod default
    EDGAR_MAX_CONCURRENCY: int = 2
    EDGAR_MAX_RETRIES: int = 3
    EDGAR_RETRY_BACKOFF_S: str = "5,30,120"
    EDGAR_FETCH_MODE: str = "live"            # live | replay
    EDGAR_SCHEDULER_ENABLED: bool = False     # prod: true

    # Dataroma rate / retry
    DATAROMA_REQUEST_DELAY_S: float = 2.0
    DATAROMA_MAX_RETRIES: int = 2
    DATAROMA_RETRY_BACKOFF_S: str = "10,60"

    # Raw document storage root
    EDGAR_RAW_STORAGE_DIR: str = "/code/storage/edgar_raw"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
