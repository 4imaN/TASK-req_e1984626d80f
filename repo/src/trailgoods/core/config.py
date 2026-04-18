import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://trailgoods:trailgoods@localhost:5432/trailgoods"
    DATABASE_URL_SYNC: str = "postgresql+psycopg://trailgoods:trailgoods@localhost:5432/trailgoods"
    SECRET_KEY: str = "change-me"
    ENCRYPTION_MASTER_KEY_FILE: str = "/run/secrets/master.key"

    ASSET_STORAGE_ROOT: str = "/data/assets"
    BACKUP_STORAGE_ROOT: str = "/data/backups"
    PREVIEW_STORAGE_ROOT: str = "/data/previews"

    LOG_LEVEL: str = "INFO"
    WORKER_POLL_INTERVAL_SECONDS: int = 5
    SESSION_IDLE_TIMEOUT_MINUTES: int = 30
    FAILED_LOGIN_WINDOW_MINUTES: int = 15
    FAILED_LOGIN_MAX_ATTEMPTS: int = 5
    CHALLENGE_LOCKOUT_MINUTES: int = 15
    PASSWORD_HISTORY_COUNT: int = 5

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_encryption_key(self) -> bytes:
        key_path = Path(self.ENCRYPTION_MASTER_KEY_FILE)
        if key_path.exists():
            raw = key_path.read_bytes().strip()
            if len(raw) == 64:
                return bytes.fromhex(raw.decode())
            if len(raw) == 32:
                return raw
            raise ValueError("Master key must be 32 bytes raw or 64 hex chars")
        env_key = os.environ.get("ENCRYPTION_MASTER_KEY")
        if env_key:
            return bytes.fromhex(env_key)
        raise ValueError("No encryption master key found")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(s: Settings) -> None:
    global _settings
    _settings = s
