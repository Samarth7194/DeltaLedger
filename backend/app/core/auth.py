from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

Role = Literal["analyst", "reviewer", "admin"]
ROLE_RANK: dict[Role, int] = {"analyst": 1, "reviewer": 2, "admin": 3}

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthPrincipal:
    subject: str
    role: Role
    auth_disabled: bool = False


def create_access_token(
    *,
    subject: str,
    role: Role,
    settings: Settings,
    issued_at: datetime | None = None,
) -> str:
    if not settings.auth_secret_key:
        raise ValueError("AUTH_SECRET_KEY is required to create access tokens.")
    now = issued_at or datetime.now(UTC)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.auth_token_ttl_seconds)).timestamp()),
    }
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload, settings.auth_secret_key)
    return f"{encoded_payload}.{signature}"


def verify_access_token(token: str, settings: Settings) -> AuthPrincipal:
    if not settings.auth_secret_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Auth is not configured.",
        )
    try:
        encoded_payload, signature = token.split(".", 1)
        expected_signature = _sign(encoded_payload, settings.auth_secret_key)
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("invalid signature")
        payload = json.loads(_b64decode(encoded_payload))
        subject = str(payload["sub"])
        role = str(payload["role"])
        expires_at = int(payload["exp"])
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token.",
        ) from exc
    if role not in ROLE_RANK:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid role.")
    if datetime.now(UTC).timestamp() >= expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired.")
    return AuthPrincipal(subject=subject, role=role)  # type: ignore[arg-type]


def require_role(minimum_role: Role):
    async def dependency(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> AuthPrincipal:
        if not settings.auth_enabled:
            return AuthPrincipal(subject="local-dev", role="admin", auth_disabled=True)
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        principal = verify_access_token(credentials.credentials, settings)
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum_role]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
        return principal

    return dependency


def _sign(encoded_payload: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")
