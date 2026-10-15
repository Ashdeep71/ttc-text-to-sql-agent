"""Settings read from environment variables and .env.

The .env path is absolute (the project root), because Claude Desktop starts the
MCP server from its own working directory, not this project's.
"""

from pathlib import Path

from psycopg.conninfo import make_conninfo
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="TRANSITQUERY_",   # TRANSITQUERY_DB_HOST sets db_host, and so on
        extra="ignore",               # .env also holds variables for other parts (OpenAI, Docker)
    )

    # Database: always the read-only role (db/init/02_roles.sql), never the admin user.
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "postgres"
    db_user: str = "transitquery_ro"
    # Same variable the DB container uses to set the role's password (04_roles_password.sh).
    db_password: SecretStr = Field(validation_alias="TRANSITQUERY_RO_PASSWORD")

    # Per-query limit, set with SET LOCAL. The role's own 5s default is the backstop.
    statement_timeout_ms: int = 5000

    # MCP server: stdio for Claude Desktop, streamable-http for Docker and the API.
    mcp_transport: str = "stdio"
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8001

    @property
    def conninfo(self) -> str:
        """Connection string for psycopg; make_conninfo quotes the password safely."""
        return make_conninfo(
            host=self.db_host,
            port=self.db_port,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password.get_secret_value(),
        )


def get_settings() -> Settings:
    return Settings()
