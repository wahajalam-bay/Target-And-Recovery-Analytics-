"""Settings read from environment variables (loaded from backend/.env)."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing environment variable {name}. Copy backend/.env.example "
            f"to backend/.env and fill it in.")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = field(default_factory=lambda: _required("REDSHIFT_HOST"))
    port: int = field(default_factory=lambda: int(os.environ.get("REDSHIFT_PORT", "5439")))
    database: str = field(default_factory=lambda: _required("REDSHIFT_DATABASE"))
    user: str = field(default_factory=lambda: _required("REDSHIFT_USER"))
    password: str = field(default_factory=lambda: _required("REDSHIFT_PASSWORD"), repr=False)
    tenant_id: int = field(default_factory=lambda: int(os.environ.get("PROPONE_TENANT_ID", "1")))
    # users.id where the visible hierarchy starts (3 = Arman Yousaf). People above stay in the maths.
    hierarchy_root_user_id: int = field(default_factory=lambda: int(os.environ.get("HIERARCHY_ROOT_USER_ID", "3")))
    refresh_seconds: int = field(default_factory=lambda: int(os.environ.get("REFRESH_SECONDS", "60")))
    pool_size: int = field(default_factory=lambda: int(os.environ.get("DB_POOL_SIZE", "4")))
    query_timeout: int = field(default_factory=lambda: int(os.environ.get("DB_TIMEOUT_SECONDS", "120")))
    # Seconds to wait for the TCP connection to Redshift before giving up (unreachable network).
    connect_timeout: int = field(default_factory=lambda: int(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "8")))
    # Optional login for the whole dashboard (set both to enable). Required when exposed via a tunnel.
    dashboard_user: str = field(default_factory=lambda: os.environ.get("DASHBOARD_USER", "").strip())
    dashboard_password: str = field(default_factory=lambda: os.environ.get("DASHBOARD_PASSWORD", ""), repr=False)
    cors_origins: tuple = field(default_factory=lambda: tuple(
        o.strip() for o in os.environ.get(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()))


settings = Settings()
