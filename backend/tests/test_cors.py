from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app

PRODUCTION_FRONTEND_ORIGIN = "https://delta-ledger.vercel.app"


def test_frontend_development_origin_is_allowed(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "GET",
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_production_auth_token_preflight_allows_json_post(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", PRODUCTION_FRONTEND_ORIGIN)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.options(
                "/api/v1/auth/token",
                headers={
                    "Origin": PRODUCTION_FRONTEND_ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "content-type",
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PRODUCTION_FRONTEND_ORIGIN
    assert "post" in response.headers["access-control-allow-methods"].lower()
    assert "content-type" in response.headers["access-control-allow-headers"].lower()


def test_production_protected_api_preflight_allows_authorization_header(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", PRODUCTION_FRONTEND_ORIGIN)
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.options(
                "/api/v1/companies",
                headers={
                    "Origin": PRODUCTION_FRONTEND_ORIGIN,
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization",
                },
            )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == PRODUCTION_FRONTEND_ORIGIN
    assert "get" in response.headers["access-control-allow-methods"].lower()
    assert "authorization" in response.headers["access-control-allow-headers"].lower()
