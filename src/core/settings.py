from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    __pydantic_extra__ = True

    # Database
    DATABASE_URL: str
    FIREBASE_CREDENTIALS: str
    JWT_SECRET_KEY: str
    
    ADMIN_NAME: str
    ADMIN_EMAIL: str
    ADMIN_PASSWORD: str

    # Runpod
    RUNPOD_API_KEY: str
    RUNPOD_ENDPOINT: str

    # LLM Configuration
    LLM_PROVIDER: str
    LLM_MODEL: str
    LLM_API_BASE_URL: str
    LLM_API_KEY: str
    LLM_MAX_TOKENS: int = 8192
    
    # SARVAM
    SARVAM_API_KEY: str

    # Google Vertex AI
    DISCOVERY_PROJECT_ID: str
    DISCOVERY_LOCATION: str
    DISCOVERY_COLLECTION: str
    DISCOVERY_ENGINE_ID: str
    DISCOVERY_SERVING_CONFIG: str
    DISCOVERY_PAGE_SIZE: str
    GOOGLE_APPLICATION_CREDENTIALS_JSON: str

    # CORS
    ALLOWED_ORIGINS: str = ""

    @computed_field
    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore"
    )


settings = Settings()