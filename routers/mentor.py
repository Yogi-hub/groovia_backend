# routers/mentor.py
# Authenticated endpoints for the logged-in mentor's own calendar connection.
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import db
import nylas_client
from auth import AuthUser, get_current_user

logger = logging.getLogger("immigroov.routers.mentor")

router = APIRouter(prefix="/mentor", tags=["mentor"])


@router.get("/me")
def get_my_mentor(user: AuthUser = Depends(get_current_user)):
    """Returns the mentor row linked to the logged-in user, or 404 if they're not a mentor."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    return mentor


@router.get("/nylas/connect-url")
def get_connect_url(redirect_uri: str, user: AuthUser = Depends(get_current_user)):
    """Returns the Nylas Hosted Auth URL to send the mentor's browser to."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    state = nylas_client.sign_state(mentor["id"])
    return {"url": nylas_client.build_auth_url(redirect_uri, state)}


class NylasCallbackBody(BaseModel):
    code: str
    state: str
    redirect_uri: str


@router.post("/nylas/callback")
def nylas_callback(body: NylasCallbackBody):
    """Completes the OAuth flow: exchanges the code for a grant and stores it on
    the mentor row identified by the signed `state`. No user session required —
    the state signature is the proof of which mentor initiated the connect flow."""
    mentor_id = nylas_client.verify_state(body.state)
    if not mentor_id:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    try:
        token = nylas_client.exchange_code(body.code, body.redirect_uri)
    except Exception:
        logger.exception("Nylas code exchange failed")
        raise HTTPException(status_code=502, detail="Failed to connect calendar")

    grant_id = token.get("grant_id")
    email = token.get("email")
    if not grant_id:
        raise HTTPException(status_code=502, detail="Nylas did not return a grant")

    try:
        calendar_id = nylas_client.primary_calendar_id(grant_id)
    except Exception:
        logger.exception("Failed to fetch calendars for grant %s", grant_id)
        calendar_id = None

    db.set_mentor_nylas_connection(mentor_id, grant_id=grant_id, calendar_id=calendar_id, email=email)
    return {"connected": True, "email": email}
