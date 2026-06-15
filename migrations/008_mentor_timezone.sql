-- 008_mentor_timezone.sql
-- Mentor's home timezone — used to build their default weekly availability window
-- (Mon-Fri 09:00-17:00 in this timezone) and to localize booking confirmation emails.
-- Run in: Supabase Dashboard -> SQL Editor -> New query -> paste -> Run

ALTER TABLE mentors
  ADD COLUMN IF NOT EXISTS timezone TEXT NOT NULL DEFAULT 'UTC';
