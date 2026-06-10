# routers/auth.py
# Public auth helpers — no token required.
import logging

from fastapi import APIRouter, Query, Request

import db
from rate_limit import limiter

logger = logging.getLogger("immigroov.routers.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/check-email")
@limiter.limit("10/minute")
def check_email(request: Request, email: str = Query(..., min_length=3, max_length=320)):
    """Returns {exists: bool}. Used by the signup form to redirect duplicates to /login.
    Rate-limited per IP to slow down enumeration probing."""
    return {"exists": db.email_is_registered(email)}
