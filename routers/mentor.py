import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

import db
import nylas_client
from auth import AuthUser, get_current_user

logger = logging.getLogger("immigroov.routers.mentor")

router = APIRouter(prefix="/mentor", tags=["mentor"])


@router.get("/me")
def get_my_mentor(user: AuthUser = Depends(get_current_user)):
    """Returns the mentor row linked to the logged-in user, or 404 if not a mentor."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    return mentor


# ── Initial signup ─────────────────────────────────────────────────────────────

class MentorSignupBody(BaseModel):
    display_name: str
    headline: Optional[str] = None
    timezone: str = "UTC"
    agreed_to_mentor_terms: bool = False
    expertise_country_codes: list[str] = []
    languages: list[str] = []
    professional_domains: list[str] = []
    years_lived_experience: Optional[int] = None
    bio: Optional[str] = None
    linkedin_url: Optional[str] = None
    youtube_url: Optional[str] = None
    instagram_url: Optional[str] = None
    session_duration_minutes: int = 60

    @field_validator("session_duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v not in (30, 60, 90):
            raise ValueError("session_duration_minutes must be 30, 60, or 90")
        return v

    @field_validator("years_lived_experience")
    @classmethod
    def validate_years(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 60):
            raise ValueError("years_lived_experience must be between 0 and 60")
        return v


@router.post("/signup")
def mentor_signup(body: MentorSignupBody, user: AuthUser = Depends(get_current_user)):
    """Self-service mentor signup: creates a new mentor row, pending admin review."""
    if db.get_mentor_by_profile_id(user.id):
        raise HTTPException(status_code=409, detail="This account is already linked to a mentor profile")
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=400, detail="Display name is required")
    if not body.agreed_to_mentor_terms:
        raise HTTPException(status_code=400, detail="You must accept the mentor agreement")
    if not body.expertise_country_codes:
        raise HTTPException(status_code=400, detail="Select at least one country of expertise")
    if not body.languages:
        raise HTTPException(status_code=400, detail="Select at least one language")
    if body.years_lived_experience is None:
        raise HTTPException(status_code=400, detail="Years of lived experience is required")
    return db.create_mentor_signup(
        user.id,
        display_name=display_name,
        headline=(body.headline or "").strip() or None,
        timezone_name=body.timezone,
        expertise_country_codes=body.expertise_country_codes,
        languages=body.languages,
        professional_domains=body.professional_domains,
        years_lived_experience=body.years_lived_experience,
        bio=(body.bio or "").strip() or None,
        linkedin_url=(body.linkedin_url or "").strip() or None,
        youtube_url=(body.youtube_url or "").strip() or None,
        instagram_url=(body.instagram_url or "").strip() or None,
        session_duration_minutes=body.session_duration_minutes,
    )


# ── Profile editing ────────────────────────────────────────────────────────────

class ProfileUpdateBody(BaseModel):
    display_name: Optional[str] = None
    headline: Optional[str] = None
    bio: Optional[str] = None
    languages: Optional[list[str]] = None
    linkedin_url: Optional[str] = None
    youtube_url: Optional[str] = None
    instagram_url: Optional[str] = None
    timezone: Optional[str] = None
    session_duration_minutes: Optional[int] = None

    @field_validator("session_duration_minutes")
    @classmethod
    def validate_duration(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in (30, 60, 90):
            raise ValueError("session_duration_minutes must be 30, 60, or 90")
        return v


@router.post("/profile")
def update_profile(body: ProfileUpdateBody, user: AuthUser = Depends(get_current_user)):
    """Update non-critical mentor profile fields (no re-approval required)."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    fields: dict[str, Any] = {}
    if body.display_name is not None:
        fields["display_name"] = body.display_name.strip() or mentor["display_name"]
    if body.headline is not None:
        fields["headline"] = body.headline.strip() or None
    if body.bio is not None:
        fields["bio"] = body.bio.strip() or None
    if body.languages is not None:
        fields["languages"] = body.languages
    if body.linkedin_url is not None:
        fields["linkedin_url"] = body.linkedin_url.strip() or None
    if body.youtube_url is not None:
        fields["youtube_url"] = body.youtube_url.strip() or None
    if body.instagram_url is not None:
        fields["instagram_url"] = body.instagram_url.strip() or None
    if body.timezone is not None:
        fields["timezone"] = body.timezone
    if body.session_duration_minutes is not None:
        fields["session_duration_minutes"] = body.session_duration_minutes
    try:
        return db.update_mentor_profile(mentor["id"], fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CriticalUpdateBody(BaseModel):
    expertise_country_codes: Optional[list[str]] = None
    years_lived_experience: Optional[int] = None
    professional_domains: Optional[list[str]] = None

    @field_validator("years_lived_experience")
    @classmethod
    def validate_years(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 0 or v > 60):
            raise ValueError("years_lived_experience must be between 0 and 60")
        return v


@router.post("/profile/critical")
def update_critical_fields(body: CriticalUpdateBody, user: AuthUser = Depends(get_current_user)):
    """Update expertise fields — resets mentor status to pending_review for re-approval."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    fields: dict[str, Any] = {}
    if body.expertise_country_codes is not None:
        if not body.expertise_country_codes:
            raise HTTPException(status_code=400, detail="Select at least one country of expertise")
        fields["expertise_country_codes"] = body.expertise_country_codes
    if body.years_lived_experience is not None:
        fields["years_lived_experience"] = body.years_lived_experience
    if body.professional_domains is not None:
        fields["professional_domains"] = body.professional_domains
    try:
        return db.update_mentor_critical_fields(mentor["id"], fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Availability ───────────────────────────────────────────────────────────────

class AvailabilitySlot(BaseModel):
    day_of_week: int   # 0=Mon … 6=Sun
    start_time: str    # "HH:MM"
    end_time: str      # "HH:MM"


class AvailabilityBody(BaseModel):
    slots: list[AvailabilitySlot]
    session_duration_minutes: int = 60
    availability_type: str = "manual"

    @field_validator("session_duration_minutes")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v not in (30, 60, 90):
            raise ValueError("session_duration_minutes must be 30, 60, or 90")
        return v


@router.get("/availability")
def get_availability(user: AuthUser = Depends(get_current_user)):
    """Return this mentor's weekly availability slots."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    return {
        "slots": db.get_mentor_availability(mentor["id"]),
        "session_duration_minutes": mentor.get("session_duration_minutes", 60),
        "availability_type": mentor.get("availability_type"),
    }


@router.post("/availability")
def set_availability(body: AvailabilityBody, user: AuthUser = Depends(get_current_user)):
    """Replace all weekly availability slots for this mentor."""
    mentor = db.get_mentor_by_profile_id(user.id)
    if not mentor:
        raise HTTPException(status_code=404, detail="No mentor profile for this account")
    slots = [s.model_dump() for s in body.slots]
    inserted = db.set_mentor_availability(
        mentor["id"],
        slots=slots,
        session_duration_minutes=body.session_duration_minutes,
        availability_type=body.availability_type,
    )
    return {"saved": len(inserted), "session_duration_minutes": body.session_duration_minutes}


# ── Nylas calendar OAuth ───────────────────────────────────────────────────────

@router.get("/nylas/connect-url")
def get_connect_url(redirect_uri: str, user: AuthUser = Depends(get_current_user)):
    """Returns the Nylas Hosted Auth URL to begin the calendar OAuth flow."""
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
    """Completes the Nylas OAuth flow and stores the grant on the mentor row."""
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
    # Mark availability type as calendar since they just connected.
    db.set_mentor_availability(mentor_id, slots=[], session_duration_minutes=60, availability_type="calendar")
    return {"connected": True, "email": email}
