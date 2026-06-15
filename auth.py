# auth.py
# JWT validation for Supabase-issued user tokens.
# Local verification (no network round-trip) using SUPABASE_JWT_SECRET.

import logging
from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

logger = logging.getLogger("immigroov.auth")

# auto_error=False so we can build optional-auth endpoints (guest mode still works)
_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthUser:
    """A verified Supabase user. Only what we actually need downstream."""
    id: str           # auth.users.id (UUID as string)
    email: str
    role: str         # supabase auth role, e.g. 'authenticated'


def _decode(token: str) -> dict:
    """Verify JWT signature + claims with the project's JWT secret."""
    return jwt.decode(
        token,
        config.SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        audience="authenticated",  # Supabase issues tokens with this audience for logged-in users
        options={"require": ["exp", "sub", "email"]},
    )


def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> AuthUser:
    """Required-auth dependency. Raises 401 if missing/invalid token."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = _decode(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.warning("Invalid JWT: %s", e)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return AuthUser(
        id=payload["sub"],
        email=payload["email"],
        role=payload.get("role", "authenticated"),
    )


def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[AuthUser]:
    """Optional-auth dependency. Returns None for guests, AuthUser when authenticated.
    Use on endpoints that work both ways (e.g. /chat allows guest threads)."""
    if creds is None:
        return None
    try:
        payload = _decode(creds.credentials)
    except jwt.InvalidTokenError:
        return None
    return AuthUser(
        id=payload["sub"],
        email=payload["email"],
        role=payload.get("role", "authenticated"),
    )


def require_admin(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    """Dependency that raises 403 unless the caller's profiles.role is 'admin'."""
    import db as _db  # local import avoids circular dependency at module level
    if _db.get_profile_role(user.id) != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def attach_user_to_request(request: Request, user: Optional[AuthUser]) -> None:
    """Stash the user on request.state so handlers/middleware can read it."""
    request.state.user = user
