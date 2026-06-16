-- 010_mentor_profile_edit.sql
-- Supports rich mentor profile, re-approval on critical edits, and manual weekly availability.

ALTER TABLE mentors
  ADD COLUMN IF NOT EXISTS availability_type  TEXT,         -- 'calendar' | 'manual' | NULL
  ADD COLUMN IF NOT EXISTS submission_count   INTEGER NOT NULL DEFAULT 1;

-- Weekly recurring availability slots (used when availability_type = 'manual').
-- Each row is a 30-minute block that the mentor marked as available.
-- day_of_week: 0 = Monday … 6 = Sunday
CREATE TABLE IF NOT EXISTS mentor_availability (
  id           UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  mentor_id    UUID    NOT NULL REFERENCES mentors(id) ON DELETE CASCADE,
  day_of_week  SMALLINT NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
  start_time   TIME    NOT NULL,
  end_time     TIME    NOT NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (mentor_id, day_of_week, start_time)
);

CREATE INDEX IF NOT EXISTS idx_mentor_availability_mentor
  ON mentor_availability(mentor_id, day_of_week);

-- RLS: mentors manage their own slots; service-role bypasses.
ALTER TABLE mentor_availability ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Mentor manages own availability" ON mentor_availability;
CREATE POLICY "Mentor manages own availability"
  ON mentor_availability
  USING (
    mentor_id IN (
      SELECT id FROM mentors WHERE profile_id = auth.uid()
    )
  );
