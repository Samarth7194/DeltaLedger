from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_service_metadata() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["service"] == "DeltaLedger AI"


def test_ready_endpoint_returns_safe_configuration_status() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/ready")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert "configuration" in payload["checks"]
        assert "database_url" not in str(payload).lower()
