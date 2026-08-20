from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.routes import auth
from app.core.auth import AuthPrincipal, create_access_token, require_role
from app.core.config import Settings, get_settings
from app.main import create_app

SECRET = "0123456789abcdef0123456789abcdef"


def test_access_token_verification_rejects_expired_token() -> None:
    settings = Settings(auth_enabled=True, auth_secret_key=SECRET, auth_token_ttl_seconds=60)
    token = create_access_token(
        subject="reviewer@example.com",
        role="reviewer",
        settings=settings,
        issued_at=datetime.now(UTC) - timedelta(minutes=2),
    )

    app = _auth_test_app(settings)
    response = TestClient(app).get(
        "/reviewer",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Token expired."


def test_reviewer_role_can_access_reviewer_route() -> None:
    settings = Settings(auth_enabled=True, auth_secret_key=SECRET)
    token = create_access_token(
        subject="reviewer@example.com",
        role="reviewer",
        settings=settings,
    )

    response = TestClient(_auth_test_app(settings)).get(
        "/reviewer",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"role": "reviewer", "subject": "reviewer@example.com"}


def test_analyst_role_cannot_access_reviewer_route() -> None:
    settings = Settings(auth_enabled=True, auth_secret_key=SECRET)
    token = create_access_token(
        subject="analyst@example.com",
        role="analyst",
        settings=settings,
    )

    response = TestClient(_auth_test_app(settings)).get(
        "/reviewer",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_auth_enabled_route_requires_bearer_token() -> None:
    settings = Settings(auth_enabled=True, auth_secret_key=SECRET)

    response = TestClient(_auth_test_app(settings)).get("/reviewer")

    assert response.status_code == 401


def test_auth_disabled_allows_local_admin_principal() -> None:
    response = TestClient(_auth_test_app(Settings(auth_enabled=False))).get("/reviewer")

    assert response.status_code == 200
    assert response.json() == {"role": "admin", "subject": "local-dev"}


def test_auth_token_endpoint_issues_signed_bearer_token() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_secret_key=SECRET,
        auth_login_username="demo",
        auth_login_password="portfolio-password-1234567890",
        auth_login_role="reviewer",
    )
    client = TestClient(_auth_token_test_app(settings))

    token_response = client.post(
        "/auth/token",
        json={"username": "demo", "password": "portfolio-password-1234567890"},
    )

    assert token_response.status_code == 200
    payload = token_response.json()["data"]
    assert payload["token_type"] == "bearer"
    assert payload["subject"] == "demo"
    assert payload["role"] == "reviewer"
    assert len(payload["access_token"].split(".")) == 2

    protected_response = client.get(
        "/reviewer",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert protected_response.status_code == 200
    assert protected_response.json() == {"role": "reviewer", "subject": "demo"}


def test_auth_token_endpoint_rejects_invalid_credentials() -> None:
    settings = Settings(
        auth_enabled=True,
        auth_secret_key=SECRET,
        auth_login_username="demo",
        auth_login_password="portfolio-password-1234567890",
    )

    response = TestClient(_auth_token_test_app(settings)).post(
        "/auth/token",
        json={"username": "demo", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password."


def test_cors_allows_authorization_header(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://example.vercel.app")
    try:
        response = TestClient(create_app()).options(
            "/api/v1/companies",
            headers={
                "Origin": "https://example.vercel.app",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


def _auth_test_app(settings: Settings) -> FastAPI:
    app = FastAPI()

    async def override_settings() -> Settings:
        return settings

    app.dependency_overrides[get_settings] = override_settings

    @app.get("/reviewer")
    async def reviewer_route(
        principal: Annotated[AuthPrincipal, Depends(require_role("reviewer"))],
    ) -> dict[str, str]:
        return {"role": principal.role, "subject": principal.subject}

    return app


def _auth_token_test_app(settings: Settings) -> FastAPI:
    app = _auth_test_app(settings)
    app.include_router(auth.router)
    return app
