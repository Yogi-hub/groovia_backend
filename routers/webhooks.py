# routers/webhooks.py
# Inbound webhook receivers. Pattern: verify signature → append to webhook_events →
# process idempotently → mark processed (or store the error for replay).
import asyncio
import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request

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

# Lifecycle-tail events carry partial payloads — update the status only, never
# overwrite the row's details with NULLs.
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
