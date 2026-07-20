"""
Authentication — validates Supabase-issued JWTs and resolves the current user.

Supabase signs user access tokens with an asymmetric key (ES256), verified
against the project's public JWKS endpoint. Legacy HS256 tokens signed with the
shared JWT secret are also accepted, so both signing configurations work.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
if not SUPABASE_JWT_SECRET:
    raise RuntimeError("SUPABASE_JWT_SECRET is not set in environment")

SUPABASE_URL = os.getenv(
    "SUPABASE_URL", "https://pyvpxqtfikctmslffmvt.supabase.co"
).rstrip("/")

# Caches the fetched key set, so this hits the network only on the first token
# (and when Supabase rotates its signing keys), not on every request.
_jwk_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")

security = HTTPBearer()


def _decode_token(token: str) -> dict:
    """Verify a Supabase JWT and return its claims.

    ES256/RS256 (Supabase's default asymmetric signing) is checked against the
    project's JWKS; HS256 against the legacy shared secret. Blocking on the JWKS
    fetch when the cache is cold — call it from a thread in async code.
    """
    alg = jwt.get_unverified_header(token).get("alg", "")
    if alg == "HS256":
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    signing_key = _jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["ES256", "RS256"],
        options={"verify_aud": False},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the Supabase JWT, extract the user id (``sub``), return the User."""
    try:
        # Run the (possibly blocking) verification off the event loop.
        payload = await asyncio.to_thread(_decode_token, credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )

    try:
        user_id_parsed = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )

    stmt = select(User).where(User.id == user_id_parsed)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
        )
    return user
