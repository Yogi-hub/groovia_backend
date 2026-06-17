# routers/mentors.py
import logging
import time
from datetime import datetime, timezone as dt_timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr

import db
import nylas_client
from auth import AuthUser, get_current_user_optional

logger = logging.getLogger("immigroov.routers.mentors")

router = APIRouter(prefix="/mentors", tags=["mentors"])

# Fields that must never leave the backend in a public response.
_PRIVATE_FIELDS = {"nylas_grant_id", "nylas_calendar_id", "nylas_email", "profile_id"}


@router.get("")
def list_mentors(
    country: Optional[str] = Query(None, min_length=2, max_length=2, description="ISO 3166-1 alpha-2"),
    category: Optional[str] = None,
    q: Optional[str] = Query(None, description="Free-text keyword to match against headline"),
    limit: int = Query(50, ge=1, le=100),
):
    """Public mentor browse — returns approved + active mentors with optional filters."""
    try:
        rows = db.list_active_mentors(
            country_code=country,
            category=category,
            profile_keyword=q,
            limit=limit,
        )
        return {"mentors": rows, "count": len(rows)}
    except Exception:
        logger.exception("list_mentors failed")
        raise HTTPException(status_code=500, detail="Failed to load mentors")


@router.get("/{slug}")
def get_mentor(slug: str):
    """Public mentor profile by slug."""
    mentor = db.get_mentor_by_slug(slug)
    if not mentor:
        raise HTTPException(status_code=404, detail="Mentor not found")
    public = {k: v for k, v in mentor.items() if k not in _PRIVATE_FIELDS}
    # Expose a safe boolean so the frontend can decide whether to show the scheduler.
    public["has_calendar"] = bool(mentor.get("nylas_grant_id") and mentor.get("nylas_calendar_id"))
    return public


def _mentor_with_calendar(slug: str) -> dict:
    mentor = db.get_mentor_by_slug(slug)
    if not mentor:
        raise HTTPException(status_code=404, detail="Mentor not found")
    if not mentor.get("nylas_grant_id") or not mentor.get("nylas_calendar_id"):
        raise HTTPException(status_code=409, detail="This mentor hasn't connected their calendar yet")
    return mentor


@router.get("/{slug}/availability")
def get_availability(slug: str, duration: Optional[int] = Query(None, ge=15, le=120)):
    """Open slots for the next two weeks, computed live against the mentor's
    connected calendar. `duration` defaults to the mentor's configured session length."""
    mentor = _mentor_with_calendar(slug)
    duration_minutes = duration or mentor["session_duration_minutes"]

    now = int(time.time())
    try:
        slots = nylas_client.get_availability(
            email=mentor["nylas_email"],
            calendar_id=mentor["nylas_calendar_id"],
            timezone=mentor["timezone"],
            duration_minutes=duration_minutes,
            start_time=now,
            end_time=now + nylas_client.AVAILABILITY_WINDOW_DAYS * 86400,
        )
    except Exception:
        logger.exception("Availability lookup failed for mentor %s", slug)
        raise HTTPException(status_code=502, detail="Could not load availability")

    return {
        "duration_minutes": duration_minutes,
        "mentor_timezone": mentor["timezone"],
        "slots": [{"start_time": s["start_time"], "end_time": s["end_time"]} for s in slots],
    }


def _format_local(ts: int, tz_name: str) -> str:
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = dt_timezone.utc
    return datetime.fromtimestamp(ts, tz=tz).strftime("%a, %d %b %Y, %H:%M %Z")


class BookingRequest(BaseModel):
    start_time: int  # unix seconds, must be a slot returned by /availability
    candidate_name: str
    candidate_email: EmailStr
    candidate_timezone: str = "UTC"
    notes: Optional[str] = None


@router.post("/{slug}/book")
def book_session(slug: str, body: BookingRequest, user: Optional[AuthUser] = Depends(get_current_user_optional)):
    """Books a session: creates a video-enabled calendar event on the mentor's
    calendar via Nylas, emails both parties, and records the booking."""
    mentor = _mentor_with_calendar(slug)
    duration_minutes = mentor["session_duration_minutes"]
    end_time = body.start_time + duration_minutes * 60

    try:
        event = nylas_client.create_event(
            grant_id=mentor["nylas_grant_id"],
            calendar_id=mentor["nylas_calendar_id"],
            title=f"Immigroov session: {mentor['display_name']} & {body.candidate_name}",
            start_time=body.start_time,
            end_time=end_time,
            mentor_email=mentor["nylas_email"],
            candidate_email=body.candidate_email,
            candidate_name=body.candidate_name,
        )
    except Exception:
        logger.exception("Event creation failed for mentor %s", slug)
        raise HTTPException(status_code=502, detail="Could not create the booking")

    meeting_url = (event.get("conferencing") or {}).get("details", {}).get("url")
    mentor_when = _format_local(body.start_time, mentor["timezone"])
    candidate_when = _format_local(body.start_time, body.candidate_timezone)

    try:
        notes_html = f"<p><b>Notes from {body.candidate_name}:</b><br>{body.notes}</p>" if body.notes else ""
        nylas_client.send_email(
            grant_id=mentor["nylas_grant_id"],
            to=[{"email": body.candidate_email, "name": body.candidate_name}],
            subject=f"Confirmed: your session with {mentor['display_name']}",
            body_html=(
                f"<p>Hi {body.candidate_name},</p>"
                f"<p>Your session with <b>{mentor['display_name']}</b> is confirmed for "
                f"<b>{candidate_when}</b> (your local time).</p>"
                + (f"<p>Video call link: <a href='{meeting_url}'>{meeting_url}</a></p>" if meeting_url else "")
                + "<p>See you there!</p>"
            ),
        )
        nylas_client.send_email(
            grant_id=mentor["nylas_grant_id"],
            to=[{"email": mentor["nylas_email"], "name": mentor["display_name"]}],
            subject=f"New booking: {body.candidate_name}",
            body_html=(
                f"<p>Hi {mentor['display_name']},</p>"
                f"<p>{body.candidate_name} ({body.candidate_email}) booked a session with you for "
                f"<b>{mentor_when}</b> (your local time).</p>"
                + (f"<p>Video call link: <a href='{meeting_url}'>{meeting_url}</a></p>" if meeting_url else "")
                + notes_html
            ),
        )
    except Exception:
        logger.exception("Booking confirmation email(s) failed for mentor %s", slug)

    fields: dict = {
        "source": "nylas",
        "external_id": str(event["id"]),
        "mentor_id": mentor["id"],
        "candidate_email": body.candidate_email,
        "candidate_name": body.candidate_name,
        "title": event.get("title"),
        "scheduled_start": datetime.fromtimestamp(body.start_time, tz=dt_timezone.utc).isoformat(),
        "scheduled_end": datetime.fromtimestamp(end_time, tz=dt_timezone.utc).isoformat(),
        "attendee_timezone": body.candidate_timezone,
        "meeting_url": meeting_url,
        "status": "confirmed",
    }
    if user:
        fields["candidate_id"] = user.id
    try:
        db.upsert_booking(fields, insert_only=True)
    except Exception:
        logger.exception("Failed to record booking row for event %s", event["id"])

    return {
        "booking_id": event["id"],
        "start_time": body.start_time,
        "end_time": end_time,
        "meeting_url": meeting_url,
        "mentor_local_time": mentor_when,
        "candidate_local_time": candidate_when,
    }
