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

    @field_validator("SQLALCHEMY_DATABASE_URI", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        if isinstance(v, str):
            return v
        
        # Fallback to building from components if not provided directly
        return str(f"postgresql://{info.data.get('POSTGRES_USER')}:{info.data.get('POSTGRES_PASSWORD')}@{info.data.get('POSTGRES_SERVER')}/{info.data.get('POSTGRES_DB')}")

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
