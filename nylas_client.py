# Thin wrapper around the Nylas v3 REST API: OAuth (Hosted Auth) + calendar lookups.
import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

import httpx

import config

logger = logging.getLogger("immigroov.nylas_client")

_AUTH_URL = f"{config.NYLAS_API_URI}/v3/connect/auth"
_TOKEN_URL = f"{config.NYLAS_API_URI}/v3/connect/token"

_STATE_TTL_SECONDS = 600  # connect flow must complete within 10 minutes

# Default weekly availability window, applied in the mentor's own timezone.
AVAILABILITY_DAYS = [1, 2, 3, 4, 5]  # Mon-Fri (Nylas: 0=Sun .. 6=Sat)
AVAILABILITY_START = "09:00"
AVAILABILITY_END = "17:00"
AVAILABILITY_WINDOW_DAYS = 14  # how far ahead to offer slots
AVAILABILITY_INTERVAL_MINUTES = 30

_AUTH_HEADERS = {"Authorization": f"Bearer {config.NYLAS_API_KEY}"}


def build_auth_url(redirect_uri: str, state: str, provider: Optional[str] = None) -> str:
    """Returns the Nylas Hosted Auth URL the mentor's browser is sent to."""
    params = {
        "client_id": config.NYLAS_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "access_type": "offline",
        "state": state,
    }
    if provider:
        params["provider"] = provider
    return f"{_AUTH_URL}?{httpx.QueryParams(params)}"


def exchange_code(code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchanges an OAuth code for a grant. Returns the Nylas token response,
    which includes grant_id and the connected account's email."""
    resp = httpx.post(
        _TOKEN_URL,
        json={
            "client_id": config.NYLAS_CLIENT_ID,
            "client_secret": config.NYLAS_API_KEY,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def primary_calendar_id(grant_id: str) -> Optional[str]:
    """Returns the connected account's primary calendar id, if any."""
    resp = httpx.get(
        f"{config.NYLAS_API_URI}/v3/grants/{grant_id}/calendars",
        headers={"Authorization": f"Bearer {config.NYLAS_API_KEY}"},
        timeout=15,
    )
    resp.raise_for_status()
    calendars = resp.json().get("data", [])
    primary = next((c for c in calendars if c.get("is_primary")), None)
    return (primary or calendars[0])["id"] if calendars else None


def sign_state(mentor_id: str) -> str:
    """Signs a short-lived token binding the OAuth connect flow to a mentor row.
    The Nylas redirect carries this back to /mentor/nylas/callback, which has no
    user session — the signature is the only proof of which mentor initiated it."""
    payload = json.dumps({"mentor_id": mentor_id, "exp": int(time.time()) + _STATE_TTL_SECONDS})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    sig = hmac.new(config.NYLAS_API_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_state(token: str) -> Optional[str]:
    """Returns the mentor_id if the token is valid and unexpired, else None."""
    try:
        payload_b64, sig = token.split(".", 1)
        expected = hmac.new(config.NYLAS_API_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        if payload["exp"] < time.time():
            return None
        return payload["mentor_id"]
    except Exception:
        return None


def get_availability(
    *,
    email: str,
    calendar_id: str,
    timezone: str,
    duration_minutes: int,
    start_time: int,
    end_time: int,
) -> list[dict[str, int]]:
    """Returns open slots for one participant within [start_time, end_time] (unix seconds),
    respecting the default Mon-Fri 09:00-17:00 window in their own timezone."""
    body = {
        "start_time": start_time,
        "end_time": end_time,
        "duration_minutes": duration_minutes,
        "interval_minutes": AVAILABILITY_INTERVAL_MINUTES,
        "availability_rules": {
            "availability_method": "collective",
            "default_open_hours": [{
                "days": AVAILABILITY_DAYS,
                "timezone": timezone,
                "start": AVAILABILITY_START,
                "end": AVAILABILITY_END,
            }],
        },
        "participants": [{"email": email, "calendar_ids": [calendar_id]}],
    }
    resp = httpx.post(
        f"{config.NYLAS_API_URI}/v3/calendars/availability",
        headers=_AUTH_HEADERS,
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("data", {}).get("time_slots", [])


def create_event(
    *,
    grant_id: str,
    calendar_id: str,
    title: str,
    start_time: int,
    end_time: int,
    mentor_email: str,
    candidate_email: str,
    candidate_name: Optional[str],
) -> dict[str, Any]:
    """Creates a calendar event with auto-generated video conferencing.
    Returns the created event object (includes id + conferencing.details.url)."""
    body = {
        "title": title,
        "when": {"start_time": start_time, "end_time": end_time, "object": "timespan"},
        "participants": [
            {"email": mentor_email},
            {"email": candidate_email, "name": candidate_name} if candidate_name else {"email": candidate_email},
        ],
        "conferencing": {"provider": "Google Meet", "autocreate": {}},
    }
    resp = httpx.post(
        f"{config.NYLAS_API_URI}/v3/grants/{grant_id}/events",
        headers=_AUTH_HEADERS,
        params={"calendar_id": calendar_id},
        json=body,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json().get("data", {})


def send_email(*, grant_id: str, to: list[dict[str, str]], subject: str, body_html: str) -> None:
    """Sends an email from the mentor's connected account via the Nylas Email API."""
    resp = httpx.post(
        f"{config.NYLAS_API_URI}/v3/grants/{grant_id}/messages/send",
        headers=_AUTH_HEADERS,
        json={"to": to, "subject": subject, "body": body_html},
        timeout=20,
    )
    resp.raise_for_status()
