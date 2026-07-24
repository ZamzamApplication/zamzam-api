from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_ENV: str = "development"
    DATABASE_URL: str = "sqlite+aiosqlite:///./quran_tracker.db"
    SECRET_KEY: str = "change-this-to-a-secure-random-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    UPLOAD_DIR: str = "./uploads"
    BACKUP_DIR: str = "./backups"
    BACKUP_INTERVAL_HOURS: int = 24
    BACKUP_RETENTION_DAYS: int = 14
    CORS_ORIGINS: str = "https://zamzam-web.fly.dev,http://localhost:3000,http://127.0.0.1:3000"

    WHATSEND_API_URL: str = "http://localhost:8000/api/send"
    WHATSEND_API_GROUPS_URL: str = ""
    WHATSEND_API_KEY: str = ""
    INTEGRATION_ENCRYPTION_KEY: str = "change-this-in-production"

    # Super-admin bootstrapping is opt-in. Existing accounts are never changed.
    BOOTSTRAP_SUPERADMIN_USERNAME: str = ""
    BOOTSTRAP_SUPERADMIN_PASSWORD: str = ""

    LOGIN_RATE_LIMIT_ATTEMPTS: int = 8
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    SIGNUP_RATE_LIMIT_ATTEMPTS: int = 5
    SIGNUP_RATE_LIMIT_WINDOW_SECONDS: int = 3600

    # Enable only after real production secrets have been installed. Until then,
    # startup emits high-visibility warnings without taking the existing service down.
    STRICT_SECURITY_VALIDATION: bool = False

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def security_issues(self) -> list[str]:
        issues: list[str] = []
        if self.SECRET_KEY == "change-this-to-a-secure-random-key-in-production" or len(self.SECRET_KEY) < 32:
            issues.append("SECRET_KEY is still a placeholder or is shorter than 32 characters")
        if (
            self.INTEGRATION_ENCRYPTION_KEY == "change-this-in-production"
            or len(self.INTEGRATION_ENCRYPTION_KEY) < 32
        ):
            issues.append(
                "INTEGRATION_ENCRYPTION_KEY is still a placeholder or is shorter than 32 characters"
            )
        if "*" in self.cors_origins:
            issues.append("CORS_ORIGINS contains a wildcard")
        if self.ALGORITHM not in {"HS256", "HS384", "HS512"}:
            issues.append("ALGORITHM must be one of HS256, HS384, or HS512")
        return issues

    class Config:
        env_file = ".env"


settings = Settings()
