"""Production configuration guard (specs/deployment.md, Slice 1)."""

import importlib
import logging

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services import prod_config

GOOD_SECRET = "s" * 40
REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TAVILY_API_KEY",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
]


@pytest.fixture
def prod_env(monkeypatch):
    """A complete, valid production environment."""
    monkeypatch.setenv("APP_ENV", "production")
    for name in REQUIRED:
        monkeypatch.setenv(name, f"value-of-{name}")
    monkeypatch.setenv("JWT_SECRET", GOOD_SECRET)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    return monkeypatch


def test_valid_production_env_passes(prod_env):
    assert prod_config.production_config_problems() == []
    prod_config.enforce_production_config()  # does not raise


def test_non_production_never_enforces(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    prod_config.enforce_production_config()  # does not raise
    assert prod_config.get_jwt_secret() == prod_config.DEV_JWT_SECRET


@pytest.mark.parametrize("secret", [None, "", "dev-secret-change-me", "short" * 3])
def test_bad_jwt_secret_is_refused(prod_env, secret):
    if secret is None:
        prod_env.delenv("JWT_SECRET")
    else:
        prod_env.setenv("JWT_SECRET", secret)
    assert "JWT_SECRET" in prod_config.production_config_problems()
    with pytest.raises(prod_config.ProductionConfigError):
        prod_config.get_jwt_secret()


def test_good_jwt_secret_is_returned_in_production(prod_env):
    assert prod_config.get_jwt_secret() == GOOD_SECRET


@pytest.mark.parametrize("name", REQUIRED)
def test_missing_required_variable_is_named(prod_env, name):
    prod_env.delenv(name)
    assert name in prod_config.production_config_problems()


@pytest.mark.parametrize("key", [None, "", "not-a-fernet-key"])
def test_bad_token_encryption_key(prod_env, key):
    if key is None:
        prod_env.delenv("TOKEN_ENCRYPTION_KEY")
    else:
        prod_env.setenv("TOKEN_ENCRYPTION_KEY", key)
    assert "TOKEN_ENCRYPTION_KEY" in prod_config.production_config_problems()


@pytest.mark.parametrize(
    "url",
    [
        "http://app.example.com",
        "https://app.example.com/",
        "https://localhost:3000",
        "https://127.0.0.1",
        "app.example.com",
        "",
    ],
)
def test_bad_frontend_url(prod_env, url):
    prod_env.setenv("FRONTEND_URL", url)
    assert "FRONTEND_URL" in prod_config.production_config_problems()


def test_frontend_url_unset_is_refused(prod_env):
    prod_env.delenv("FRONTEND_URL")
    assert "FRONTEND_URL" in prod_config.production_config_problems()


def test_error_lists_names_only_never_values(prod_env):
    prod_env.setenv("JWT_SECRET", "dev-secret-change-me")
    prod_env.setenv("TOKEN_ENCRYPTION_KEY", "super-secret-bad-key-value")
    prod_env.setenv("FRONTEND_URL", "http://insecure.example.com")
    prod_env.delenv("TAVILY_API_KEY")
    with pytest.raises(prod_config.ProductionConfigError) as exc:
        prod_config.enforce_production_config()
    text = str(exc.value)
    for name in (
        "JWT_SECRET",
        "TOKEN_ENCRYPTION_KEY",
        "FRONTEND_URL",
        "TAVILY_API_KEY",
    ):
        assert name in text
    for value in (
        "dev-secret-change-me",
        "super-secret-bad-key-value",
        "insecure.example.com",
    ):
        assert value not in text


def test_startup_refuses_bad_production_config(prod_env):
    import main

    prod_env.setenv("JWT_SECRET", "dev-secret-change-me")
    with pytest.raises(prod_config.ProductionConfigError), TestClient(main.app):
        pass


def test_startup_succeeds_with_valid_production_config(prod_env):
    import main

    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200


def test_docs_kwargs(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    assert prod_config.docs_kwargs() == {}
    monkeypatch.setenv("APP_ENV", "production")
    assert prod_config.docs_kwargs() == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


def test_production_app_has_no_docs(prod_env):
    import main

    try:
        reloaded = importlib.reload(main)
        client = TestClient(reloaded.app)
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
        assert client.get("/health").status_code == 200
    finally:
        prod_env.delenv("APP_ENV")
        importlib.reload(main)
    assert TestClient(main.app).get("/openapi.json").status_code == 200


@pytest.mark.parametrize("name", ["WEB_CONCURRENCY", "UVICORN_WORKERS"])
def test_worker_count_warning(monkeypatch, name):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    assert prod_config.worker_count_warning() is None
    monkeypatch.setenv(name, "1")
    assert prod_config.worker_count_warning() is None
    monkeypatch.setenv(name, "2")
    assert "single worker" in prod_config.worker_count_warning()
    monkeypatch.setenv(name, "garbage")
    assert prod_config.worker_count_warning() is None


def test_startup_logs_worker_warning(monkeypatch, caplog):
    import main

    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with caplog.at_level(logging.WARNING), TestClient(main.app):
        pass
    assert any("single worker" in r.getMessage() for r in caplog.records)
