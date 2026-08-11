from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.services.health_checks import run_readiness_checks

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@router.get("/ready")
async def ready(response: Response) -> dict[str, object]:
    settings = get_settings()
    payload = await run_readiness_checks(settings)
    if payload["status"] != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload
