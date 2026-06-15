-- 007_nylas.sql
-- Nylas calendar integration: a mentor connects their own Google/Outlook calendar via
-- Nylas OAuth, producing a grant_id we use to check availability and create events.
-- Coexists with the existing Cal.com booking_url flow — a mentor with nylas_grant_id
-- set uses the new in-app booking flow; mentors without one keep the Cal.com redirect.
-- Run in: Supabase Dashboard -> SQL Editor -> New query -> paste -> Run

ALTER TABLE mentors
  ADD COLUMN IF NOT EXISTS nylas_grant_id          TEXT,
  ADD COLUMN IF NOT EXISTS nylas_calendar_id       TEXT,
  ADD COLUMN IF NOT EXISTS nylas_email             TEXT,
  ADD COLUMN IF NOT EXISTS calendar_connected_at   TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS session_duration_minutes INTEGER NOT NULL DEFAULT 30;

-- One grant per mentor; also lets the webhook resolve mentor <- grant_id quickly.
CREATE UNIQUE INDEX IF NOT EXISTS idx_mentors_nylas_grant
  ON mentors(nylas_grant_id) WHERE nylas_grant_id IS NOT NULL;

-- bookings.source is free-form TEXT (default 'cal.com') — 'nylas' is just a new value,
-- no schema change needed there.
