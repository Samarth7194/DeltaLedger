from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.schemas import ResponseEnvelope, ResponseMeta
from app.core.auth import create_access_token
from app.core.config import Settings, get_settings

router = APIRouter(prefix="/auth")


class TokenRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    subject: str
    role: str


@router.post("/token")
async def issue_token(
    payload: TokenRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ResponseEnvelope:
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication is disabled.",
        )
    if not settings.auth_login_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login password is not configured.",
        )
    if not _matches(payload.username, settings.auth_login_username) or not _matches(
        payload.password,
        settings.auth_login_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    token = create_access_token(
        subject=settings.auth_login_username,
        role=settings.auth_login_role,
        settings=settings,
    )
    data = TokenResponse(
        access_token=token,
        expires_in=settings.auth_token_ttl_seconds,
        subject=settings.auth_login_username,
        role=settings.auth_login_role,
    )
    return ResponseEnvelope(
        data=data.model_dump(),
        meta=ResponseMeta(request_id=getattr(request.state, "request_id", None)),
    )


def _matches(value: str, expected: str) -> bool:
    return hmac.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))
