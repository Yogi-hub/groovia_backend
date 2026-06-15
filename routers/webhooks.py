# Inbound webhook receivers: verify signature, append to webhook_events, process idempotently.
import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response

import config
import db

logger = logging.getLogger("immigroov.routers.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Cal.com triggerEvent → bookings.status
_STATUS_MAP = {
    "BOOKING_CREATED": "confirmed",
    "BOOKING_RESCHEDULED": "rescheduled",
    "BOOKING_CANCELLED": "cancelled",
    "MEETING_ENDED": "completed",
    "BOOKING_NO_SHOW_UPDATED": "no_show",
}

# Lifecycle-tail events carry partial payloads — update status only, don't null out details.
_STATUS_ONLY_EVENTS = {"MEETING_ENDED", "BOOKING_NO_SHOW_UPDATED"}


def _verify_cal_signature(raw_body: bytes, header_sig: str) -> bool:
    """Cal signs the raw body with HMAC-SHA256 of the webhook secret and sends the
    hex digest in X-Cal-Signature-256."""
    if not config.CAL_WEBHOOK_SECRET or not header_sig:
        return False
    expected = hmac.new(config.CAL_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


def _extract_booking_fields(event_type: str, payload: dict) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Map a Cal webhook payload onto a bookings row.
    Returns (fields, None) on success or (None, reason) when unresolvable —
    the raw event stays in webhook_events so it can be replayed after a fix."""
    uid = payload.get("uid") or payload.get("bookingUid") or payload.get("bookingId")
    if not uid:
        return None, "payload has no uid/bookingId"

    organizer = payload.get("organizer") or {}
    username = organizer.get("username") or ""
    mentor = db.find_mentor_by_cal_path(username)
    if not mentor:
        return None, f"no mentor matches cal username {username!r}"

    attendees = payload.get("attendees") or []
    attendee = attendees[0] if attendees else {}
    email = (attendee.get("email") or "").lower() or None
    metadata = payload.get("metadata") or {}

    fields: dict[str, Any] = {
        "source": "cal.com",
        "external_id": str(uid),
        "mentor_id": mentor["id"],
        "candidate_email": email,
        "candidate_name": attendee.get("name"),
        "title": payload.get("title") or payload.get("eventTitle"),
        "scheduled_start": payload.get("startTime"),
        "scheduled_end": payload.get("endTime"),
        "attendee_timezone": attendee.get("timeZone"),
        "meeting_url": metadata.get("videoCallUrl") or payload.get("videoCallUrl"),
        "status": _STATUS_MAP[event_type],
    }
    if email:
        candidate_id = db.get_profile_id_by_email(email)
        if candidate_id:
            fields["candidate_id"] = candidate_id
    # Present only if we ever append ?metadata[immigroov_thread_id]=... to booking links.
    thread_id = metadata.get("immigroov_thread_id")
    if thread_id:
        fields["thread_id"] = thread_id
    if event_type == "BOOKING_CANCELLED":
        fields["cancel_reason"] = payload.get("cancellationReason")
    return fields, None


@router.post("/cal")
async def cal_webhook(request: Request):
    """Receives BOOKING_CREATED / BOOKING_RESCHEDULED / BOOKING_CANCELLED /
    MEETING_ENDED from Cal.com. Always answers 200 once the event is logged —
    processing failures are stored on the event row for replay, not retried by Cal."""
    if not config.CAL_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    raw = await request.body()
    signature_ok = _verify_cal_signature(raw, request.headers.get("x-cal-signature-256", ""))

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    event_type = body.get("triggerEvent", "")
    payload = body.get("payload") or {}
    external_id = payload.get("uid") or payload.get("bookingId")

    event_id = await asyncio.to_thread(
        db.log_webhook_event,
        provider="cal.com",
        event_type=event_type,
        external_id=str(external_id) if external_id else None,
        signature_ok=signature_ok,
        payload=body,
    )

    if not signature_ok:
        # Kept in webhook_events for forensics, but never processed.
        raise HTTPException(status_code=401, detail="Invalid signature.")

    if event_type not in _STATUS_MAP:
        await asyncio.to_thread(db.mark_webhook_processed, event_id, f"ignored event {event_type}")
        return {"received": True, "ignored": True}

    def _process() -> Optional[str]:
        if event_type in _STATUS_ONLY_EVENTS:
            uid = payload.get("uid") or payload.get("bookingUid") or payload.get("bookingId")
            if not uid:
                return "payload has no uid/bookingId"
            updated = db.update_booking_status(str(uid), _STATUS_MAP[event_type])
            return None if updated else f"no booking row for uid {uid}"
        fields, reason = _extract_booking_fields(event_type, payload)
        if fields is None:
            return reason
        db.upsert_booking(fields, insert_only=(event_type == "BOOKING_CREATED"))
        return None

    try:
        error = await asyncio.to_thread(_process)
    except Exception as e:
        logger.exception("Cal webhook processing failed (event %s)", event_id)
        error = f"{type(e).__name__}: {e}"

    await asyncio.to_thread(db.mark_webhook_processed, event_id, error)
    if error:
        logger.warning("Cal webhook stored but unprocessed: %s", error)
    return {"received": True, "processed": error is None}


# Nylas event.* status -> bookings.status (event.deleted is mapped to 'cancelled' directly)
_NYLAS_STATUS_MAP = {
    "confirmed": "confirmed",
    "tentative": "confirmed",
    "cancelled": "cancelled",
}


def _verify_nylas_signature(raw_body: bytes, header_sig: str) -> bool:
    """Nylas signs the raw body with HMAC-SHA256 of the webhook secret and sends the
    hex digest in X-Nylas-Signature."""
    if not config.NYLAS_WEBHOOK_SECRET or not header_sig:
        return False
    expected = hmac.new(config.NYLAS_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header_sig.strip())


def _extract_nylas_booking_fields(event_type: str, obj: dict) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """Map a Nylas event.* webhook object onto a bookings row.
    Returns (fields, None) on success or (None, reason) when unresolvable —
    the raw event stays in webhook_events so it can be replayed after a fix."""
    event_id = obj.get("id")
    if not event_id:
        return None, "event object has no id"

    grant_id = obj.get("grant_id")
    mentor = db.find_mentor_by_nylas_grant(grant_id)
    if not mentor:
        return None, f"no mentor matches nylas grant {grant_id!r}"

    when = obj.get("when") or {}
    start = when.get("start_time")
    end = when.get("end_time")
    if start is None:
        return None, "event object has no when.start_time"

    participants = obj.get("participants") or []
    mentor_email = (mentor.get("nylas_email") or "").lower()
    attendee = next((p for p in participants if (p.get("email") or "").lower() != mentor_email), None) \
        or (participants[0] if participants else {})
    email = (attendee.get("email") or "").lower() or None

    conferencing = obj.get("conferencing") or {}
    meeting_url = (conferencing.get("details") or {}).get("url")

    status = "cancelled" if event_type == "event.deleted" else _NYLAS_STATUS_MAP.get(obj.get("status"), "confirmed")

    fields: dict[str, Any] = {
        "source": "nylas",
        "external_id": str(event_id),
        "mentor_id": mentor["id"],
        "candidate_email": email,
        "candidate_name": attendee.get("name"),
        "title": obj.get("title"),
        "scheduled_start": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
        "scheduled_end": datetime.fromtimestamp(end, tz=timezone.utc).isoformat() if end else None,
        "meeting_url": meeting_url,
        "status": status,
    }
    if email:
        candidate_id = db.get_profile_id_by_email(email)
        if candidate_id:
            fields["candidate_id"] = candidate_id
    return fields, None


@router.get("/nylas")
async def nylas_webhook_challenge(challenge: str = ""):
    """Nylas verifies a new webhook destination with a GET request carrying a
    `challenge` query param that must be echoed back as plain text."""
    return Response(content=challenge, media_type="text/plain")


@router.post("/nylas")
async def nylas_webhook(request: Request):
    """Receives event.created / event.updated / event.deleted from Nylas.
    Always answers 200 once the event is logged — processing failures are stored
    on the event row for replay, not retried by Nylas."""
    if not config.NYLAS_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured.")

    raw = await request.body()
    signature_ok = _verify_nylas_signature(raw, request.headers.get("x-nylas-signature", ""))

    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    event_type = body.get("type", "")
    data = body.get("data") or {}
    obj = data.get("object") or {}
    external_id = obj.get("id")

    event_id = await asyncio.to_thread(
        db.log_webhook_event,
        provider="nylas",
        event_type=event_type,
        external_id=str(external_id) if external_id else None,
        signature_ok=signature_ok,
        payload=body,
    )

    if not signature_ok:
        raise HTTPException(status_code=401, detail="Invalid signature.")

    if event_type not in ("event.created", "event.updated", "event.deleted"):
        await asyncio.to_thread(db.mark_webhook_processed, event_id, f"ignored event {event_type}")
        return {"received": True, "ignored": True}

    def _process() -> Optional[str]:
        fields, reason = _extract_nylas_booking_fields(event_type, obj)
        if fields is None:
            return reason
        db.upsert_booking(fields, insert_only=(event_type == "event.created"))
        return None

    try:
        error = await asyncio.to_thread(_process)
    except Exception as e:
        logger.exception("Nylas webhook processing failed (event %s)", event_id)
        error = f"{type(e).__name__}: {e}"

    await asyncio.to_thread(db.mark_webhook_processed, event_id, error)
    if error:
        logger.warning("Nylas webhook stored but unprocessed: %s", error)
    return {"received": True, "processed": error is None}
