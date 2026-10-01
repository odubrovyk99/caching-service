from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from sqlalchemy import URL

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Service configuration, read from environment variables.

    Attributes:
        postgres_host: Database host.
        postgres_port: Database port.
        postgres_user: Database user.
        postgres_password: Database password; hidden in ``repr`` and logs.
        postgres_db: Database name.
        log_level: Level for the service's stdlib logging. Validated, so a typo fails at startup.
    """

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str
    postgres_password: SecretStr
    postgres_db: str
    log_level: LogLevel = "INFO"

    @property
    def database_url(self) -> URL:
        """Build the asyncpg connection URL from the separate parts.

        Returns:
            A ``postgresql+asyncpg`` SQLAlchemy URL.
        """
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    """Load settings once per process.

    Returns:
        The cached ``Settings`` instance.
    """
    return Settings()
