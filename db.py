# Server-side Supabase client (service role) + typed query helpers. Never expose to the browser.

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from supabase import Client, create_client

import config

logger = logging.getLogger("immigroov.db")

# One module-level client. Cheap to create, but reuse it.
_supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)


def client() -> Client:
    return _supabase


# Mentors

def list_active_mentors(
    *,
    country_code: Optional[str] = None,
    category: Optional[str] = None,
    profile_keyword: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Public mentor browse query.
    All filters are AND-ed. country_code is an ISO 3166-1 alpha-2 code (e.g. 'NL')."""
    q = (
        _supabase.table("mentors")
        .select("id, slug, display_name, headline, bio, photo_url, "
                "expertise_country_codes, expertise_categories, languages, "
                "professional_domains, booking_url, years_lived_experience")
        .eq("status", "approved")
        .eq("is_active", True)
        .limit(limit)
    )
    if country_code:
        q = q.contains("expertise_country_codes", [country_code.upper()])
    if category:
        q = q.contains("expertise_categories", [category])
    if profile_keyword:
        q = q.ilike("headline", f"%{profile_keyword}%")
    return q.execute().data or []


def list_mentors_grouped_by_country(limit_per_country: int = 2) -> dict[str, list[dict[str, Any]]]:
    """Return all approved+active mentors, grouped by every ISO-2 country in their expertise.
    Used by the report flow so the LLM gets real mentor data in-prompt and never has to
    call retrieve_matching_mentors per country.
    Default is 2 — the report ends with a Mentor Directory link so users can browse more."""
    rows = (
        _supabase.table("mentors")
        .select("display_name, headline, expertise_country_codes, booking_url")
        .eq("status", "approved")
        .eq("is_active", True)
        .execute()
        .data or []
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not r.get("booking_url"):
            continue
        for code in (r.get("expertise_country_codes") or []):
            bucket = grouped.setdefault(code, [])
            if len(bucket) < limit_per_country:
                bucket.append({
                    "name": r["display_name"],
                    "headline": r.get("headline") or "",
                    "booking_url": f"{config.CAL_BASE_URL}/{r['booking_url']}",
                })
    return grouped


def mentors_available_for_country(country_code: str) -> bool:
    """Cheap existence check — does the mentors table have any approved+active mentor
    whose expertise covers this ISO-2 country code?"""
    if not country_code:
        return False
    res = (
        _supabase.table("mentors")
        .select("id")
        .eq("status", "approved")
        .eq("is_active", True)
        .contains("expertise_country_codes", [country_code.upper()])
        .limit(1)
        .execute()
    )
    return bool(res.data)


def get_mentor_by_slug(slug: str) -> Optional[dict[str, Any]]:
    res = (
        _supabase.table("mentors")
        .select("*")
        .eq("slug", slug)
        .eq("status", "approved")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# Chat threads

def upsert_chat_thread(
    *,
    thread_id: str,
    user_id: Optional[str],
    user_intent: Optional[str] = None,
    track: Optional[str] = None,
    title_seed: Optional[str] = None,
) -> None:
    """Create or update the metadata row for a LangGraph thread.
    Called from /chat after every successful turn.
    `title_seed` (first ~60 chars of the user's first real message) is only written
    when the row's title is still empty."""
    now = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "id": thread_id,
        "user_id": user_id,
        "last_message_at": now,
    }
    if user_intent is not None:
        payload["user_intent"] = user_intent
    if track is not None:
        payload["track"] = track

    try:
        _supabase.table("chat_threads").upsert(payload, on_conflict="id").execute()
        # Set title only if the row doesn't have one yet — preserves the first message snippet.
        if title_seed:
            _supabase.table("chat_threads").update({"title": title_seed[:60]}).eq("id", thread_id).is_("title", "null").execute()
    except Exception:
        logger.exception("Failed to upsert chat_thread %s", thread_id)
        # Non-fatal — chat still works without the metadata row.


def claim_thread(thread_id: str, user_id: str) -> bool:
    """Link a guest thread (user_id IS NULL) to the now-authenticated user.
    Idempotent: returns True if it linked or if it was already owned by this user."""
    try:
        res = (
            _supabase.table("chat_threads")
            .update({"user_id": user_id})
            .eq("id", thread_id)
            .is_("user_id", "null")
            .execute()
        )
        if res.data:
            return True
        # Already owned (by this user) is fine; by someone else is not.
        owner = get_thread_owner(thread_id)
        return owner == user_id
    except Exception:
        logger.exception("Failed to claim chat_thread %s for %s", thread_id, user_id)
        return False


def list_user_threads(user_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
    res = (
        _supabase.table("chat_threads")
        .select("id, title, user_intent, track, last_message_at, message_count")
        .eq("user_id", user_id)
        .eq("is_archived", False)
        .order("last_message_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def get_thread_owner(thread_id: str) -> Optional[str]:
    """Return the user_id that owns this thread, or None if no row / guest thread."""
    res = (
        _supabase.table("chat_threads")
        .select("user_id")
        .eq("id", thread_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    return res.data[0].get("user_id")


# Webhooks + bookings

def log_webhook_event(
    *,
    provider: str,
    event_type: str,
    external_id: Optional[str],
    signature_ok: bool,
    payload: dict,
) -> Optional[str]:
    """Append the raw webhook to the intake log BEFORE processing.
    Returns the event row id, or None if even logging failed."""
    try:
        res = _supabase.table("webhook_events").insert({
            "provider": provider,
            "event_type": event_type,
            "external_id": external_id,
            "signature_ok": signature_ok,
            "payload": payload,
        }).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        logger.exception("Failed to log webhook event (%s %s)", provider, event_type)
        return None


def mark_webhook_processed(event_id: Optional[str], error: Optional[str] = None) -> None:
    if not event_id:
        return
    try:
        _supabase.table("webhook_events").update({
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }).eq("id", event_id).execute()
    except Exception:
        logger.exception("Failed to mark webhook event %s processed", event_id)


def find_mentor_by_cal_path(path_or_username: str) -> Optional[dict[str, Any]]:
    """Resolve a mentor from a Cal.com organizer username or booking path.
    mentors.booking_url stores 'username/event-slug', so a prefix match works
    for both 'username' and 'username/30min'."""
    if not path_or_username:
        return None
    try:
        res = (
            _supabase.table("mentors")
            .select("id, display_name, booking_url")
            .ilike("booking_url", f"{path_or_username}%")
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception:
        logger.exception("Mentor lookup failed for cal path %r", path_or_username)
        return None


def get_mentor_by_profile_id(profile_id: str) -> Optional[dict[str, Any]]:
    """Resolve the mentor row linked to a logged-in user's profile, if any."""
    if not profile_id:
        return None
    res = (
        _supabase.table("mentors")
        .select("id, slug, display_name, nylas_grant_id, nylas_calendar_id, nylas_email, calendar_connected_at")
        .eq("profile_id", profile_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def find_mentor_by_nylas_grant(grant_id: str) -> Optional[dict[str, Any]]:
    """Resolve a mentor from the Nylas grant_id embedded in a webhook payload."""
    if not grant_id:
        return None
    try:
        res = (
            _supabase.table("mentors")
            .select("id, display_name, nylas_grant_id, nylas_email")
            .eq("nylas_grant_id", grant_id)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception:
        logger.exception("Mentor lookup failed for nylas grant %r", grant_id)
        return None


def set_mentor_nylas_connection(mentor_id: str, *, grant_id: str, calendar_id: str, email: Optional[str]) -> None:
    """Record a mentor's Nylas calendar connection after the OAuth callback."""
    _supabase.table("mentors").update({
        "nylas_grant_id": grant_id,
        "nylas_calendar_id": calendar_id,
        "nylas_email": email,
        "calendar_connected_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", mentor_id).execute()


def get_profile_id_by_email(email: str) -> Optional[str]:
    if not email:
        return None
    try:
        res = _supabase.table("profiles").select("id").eq("email", email.lower()).limit(1).execute()
        return res.data[0]["id"] if res.data else None
    except Exception:
        logger.exception("Profile lookup by email failed")
        return None


def update_booking_status(external_id: str, status: str) -> bool:
    """Status-only update for lifecycle-tail events (meeting ended, no-show).
    Returns False when no booking row exists for this uid yet."""
    res = (
        _supabase.table("bookings")
        .update({"status": status})
        .eq("external_id", external_id)
        .execute()
    )
    return bool(res.data)


def upsert_booking(fields: dict[str, Any], *, insert_only: bool = False) -> None:
    """Idempotent write keyed on external_id (the Cal booking uid).
    insert_only=True (BOOKING_CREATED) never overwrites an existing row — guards
    against out-of-order webhooks downgrading a cancelled/completed booking back
    to confirmed. Raises on failure so the caller records it in webhook_events."""
    _supabase.table("bookings").upsert(
        fields,
        on_conflict="external_id",
        ignore_duplicates=insert_only,
    ).execute()


# Profiles

def save_profile_summary_if_empty(user_id: str, summary: str) -> None:
    """Persist the agent-extracted resume summary to the user's profile, but only
    when the field is still NULL — a manual edit on the account page wins."""
    if not summary:
        return
    try:
        (
            _supabase.table("profiles")
            .update({"profile_summary": summary[:2000]})
            .eq("id", user_id)
            .is_("profile_summary", "null")
            .execute()
        )
    except Exception:
        logger.exception("Failed to save profile summary for %s", user_id)


# Auth helpers

def email_is_registered(email: str) -> bool:
    """Return True if an account with this email already exists.
    Used to give a clear UX on signup ('already registered → please sign in')."""
    res = (
        _supabase.table("profiles")
        .select("id")
        .eq("email", email.lower())
        .limit(1)
        .execute()
    )
    return bool(res.data)
