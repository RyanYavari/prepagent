"""Production configuration guard (specs/deployment.md).

With `APP_ENV=production` the app refuses to start unless required settings are
present and sane. Errors name the variables only, never their values. Outside
production nothing is enforced and local development is unchanged.
"""

import logging
import os
from urllib.parse import urlparse

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

DEV_JWT_SECRET = "dev-secret-change-me"
MIN_JWT_SECRET_LENGTH = 32

REQUIRED_VARIABLES = (
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
)

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class ProductionConfigError(Exception):
    """Production configuration is unsafe or incomplete. Message lists names only."""


def is_production() -> bool:
    return os.getenv("APP_ENV", "").strip().lower() == "production"


def _jwt_secret_ok(secret: str | None) -> bool:
    return bool(
        secret and secret != DEV_JWT_SECRET and len(secret) >= MIN_JWT_SECRET_LENGTH
    )


def _fernet_key_ok(key: str | None) -> bool:
    if not key:
        return False
    try:
        Fernet(key.encode())
    except (ValueError, TypeError):
        return False
    return True


def _frontend_url_ok(url: str | None) -> bool:
    if not url or url.endswith("/"):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and bool(host) and host not in _LOCAL_HOSTS


def production_config_problems() -> list[str]:
    """Names of the variables that make the current environment unsafe for production."""
    problems = [name for name in REQUIRED_VARIABLES if not os.getenv(name)]
    if not _jwt_secret_ok(os.getenv("JWT_SECRET")):
        problems.append("JWT_SECRET")
    if not _fernet_key_ok(os.getenv("TOKEN_ENCRYPTION_KEY")):
        problems.append("TOKEN_ENCRYPTION_KEY")
    if not _frontend_url_ok(os.getenv("FRONTEND_URL")):
        problems.append("FRONTEND_URL")
    return problems


def enforce_production_config() -> None:
    """Raise ProductionConfigError (names only) when production config is unsafe."""
    if not is_production():
        return
    problems = production_config_problems()
    if problems:
        raise ProductionConfigError(
            "Invalid production configuration; fix these variables: "
            + ", ".join(problems)
        )


def get_jwt_secret() -> str:
    """The session-signing secret.

    Production never falls back to the development default: a missing or weak secret
    raises instead of silently signing with a publicly known value.
    """
    secret = os.getenv("JWT_SECRET")
    if is_production():
        if not _jwt_secret_ok(secret):
            raise ProductionConfigError("JWT_SECRET is missing or too weak")
        assert secret is not None
        return secret
    return secret or DEV_JWT_SECRET


def docs_kwargs() -> dict:
    """FastAPI constructor arguments that switch the interactive docs off in production."""
    if is_production():
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


def worker_count_warning() -> str | None:
    """Warn when a worker count above 1 is configured (PKCE stores are per-process)."""
    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS"):
        raw = os.getenv(name)
        try:
            count = int(raw) if raw else 1
        except ValueError:
            continue
        if count > 1:
            return (
                f"{name}={count}: PrepAgent requires a single worker, because OAuth "
                "PKCE verifiers and rate limits are held in process memory"
            )
    return None
