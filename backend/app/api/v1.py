from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    analyses,
    auth,
    companies,
    comparisons,
    contradictions,
    filings,
    financial,
    health,
    retrieval,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(companies.router, tags=["companies"])
api_router.include_router(filings.router, tags=["filings"])
api_router.include_router(retrieval.router, tags=["retrieval"])
api_router.include_router(analyses.router, tags=["analyses"])
api_router.include_router(comparisons.router, tags=["comparisons"])
api_router.include_router(financial.router, tags=["financial"])
api_router.include_router(contradictions.router, tags=["contradictions"])
