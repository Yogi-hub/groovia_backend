# db.py
# Server-side Supabase client (service role) + typed query helpers.
# Service role bypasses RLS — this client must NEVER be exposed to the browser.

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
