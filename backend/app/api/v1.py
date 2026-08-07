from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import comparisons, filings, health, retrieval

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(filings.router, tags=["filings"])
api_router.include_router(retrieval.router, tags=["retrieval"])
api_router.include_router(comparisons.router, tags=["comparisons"])
