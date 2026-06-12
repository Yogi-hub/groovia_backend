-- 006_profile_summary.sql
-- Account page v2: agent-extracted (or manually edited) profile summary + phone.
-- The summary is written once by the backend after resume compression (only when
-- still NULL, so a manual edit is never overwritten) and editable by the user.
-- Run in: Supabase Dashboard → SQL Editor

ALTER TABLE profiles ADD COLUMN IF NOT EXISTS profile_summary TEXT;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS phone TEXT;
