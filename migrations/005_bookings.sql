-- 005_bookings.sql
-- Booking tracking (Cal.com webhooks now; Stripe/Razorpay webhooks reuse the same
-- intake pattern in Slice 1).
-- Also fixes a FK flaw: deleting a mentor's login account must DETACH the public
-- mentor record, not destroy it — booking history has to survive.
-- Run in: Supabase Dashboard → SQL Editor → New query → paste → Run

-- ============================================================================
-- 1. FK fix: mentors.profile_id was ON DELETE CASCADE.
--    With bookings referencing mentors, a cascading profile delete would either
--    wipe the mentor row (orphaning booking FKs) or be blocked entirely.
--    SET NULL detaches the account and keeps the mentor record for history;
--    the GDPR pipeline then anonymises display fields separately.
-- ============================================================================
ALTER TABLE mentors DROP CONSTRAINT IF EXISTS mentors_profile_id_fkey;
ALTER TABLE mentors
  ADD CONSTRAINT mentors_profile_id_fkey
  FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE SET NULL;

-- ============================================================================
-- 2. Booking lifecycle enum.
--    PRD 4.7 lists Upcoming / In Progress / Completed / Rescheduled / Cancelled /
--    No-Show. "Upcoming" and "In Progress" are time-derived (now() vs the
--    scheduled window), so only real state transitions are stored.
-- ============================================================================
DO $$ BEGIN
  CREATE TYPE booking_status AS ENUM
    ('confirmed', 'rescheduled', 'cancelled', 'completed', 'no_show');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================================
-- 3. webhook_events — append-only intake log for ALL inbound webhooks.
--    Every delivery is stored BEFORE processing. If processing fails the row
--    stays with processed_at IS NULL + error → admin can replay. This is the
--    dead-letter pattern the PRD requires for payment webhooks; Cal uses it too.
--    Service-role only: RLS enabled with no policies.
-- ============================================================================
CREATE TABLE IF NOT EXISTS webhook_events (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider      TEXT NOT NULL,               -- 'cal.com' | 'stripe' | 'razorpay'
  event_type    TEXT NOT NULL,               -- e.g. 'BOOKING_CREATED'
  external_id   TEXT,                        -- provider's object id (Cal booking uid)
  signature_ok  BOOLEAN NOT NULL DEFAULT FALSE,
  payload       JSONB NOT NULL,
  processed_at  TIMESTAMPTZ,                 -- NULL = pending or failed
  error         TEXT,
  received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_events_lookup
  ON webhook_events(provider, external_id);
CREATE INDEX IF NOT EXISTS idx_webhook_events_unprocessed
  ON webhook_events(received_at) WHERE processed_at IS NULL;

ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;
-- No policies on purpose: only the backend (service role) reads/writes this table.

-- ============================================================================
-- 4. bookings — one row per real meeting between a mentor and a candidate.
--    This is the many-to-many resolution table: one mentor ↔ many candidates,
--    one candidate ↔ many mentors, each meeting is one row with its own state.
--    Money stays OUT of this table — payments (Slice 1) will reference
--    bookings.id so one booking can have 0..n payment attempts/refunds.
-- ============================================================================
CREATE TABLE IF NOT EXISTS bookings (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source            TEXT NOT NULL DEFAULT 'cal.com',
  external_id       TEXT UNIQUE,             -- Cal booking uid; webhook idempotency key
  mentor_id         UUID NOT NULL REFERENCES mentors(id)     ON DELETE RESTRICT,
  candidate_id      UUID REFERENCES profiles(id)             ON DELETE SET NULL,
  candidate_email   TEXT,                    -- captured from Cal even for guests;
  candidate_name    TEXT,                    -- nulled by the GDPR delete pipeline
  thread_id         UUID REFERENCES chat_threads(id)         ON DELETE SET NULL,
  title             TEXT,
  scheduled_start   TIMESTAMPTZ NOT NULL,
  scheduled_end     TIMESTAMPTZ,
  attendee_timezone TEXT,
  meeting_url       TEXT,
  status            booking_status NOT NULL DEFAULT 'confirmed',
  cancel_reason     TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bookings_mentor_time
  ON bookings(mentor_id, scheduled_start DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_candidate_time
  ON bookings(candidate_id, scheduled_start DESC);
CREATE INDEX IF NOT EXISTS idx_bookings_thread
  ON bookings(thread_id);

DROP TRIGGER IF EXISTS trg_bookings_updated_at ON bookings;
CREATE TRIGGER trg_bookings_updated_at
  BEFORE UPDATE ON bookings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- 5. RLS — candidates and mentors each read their own bookings.
--    Writes happen only through the backend (service role bypasses RLS).
-- ============================================================================
ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Candidates read own bookings" ON bookings;
CREATE POLICY "Candidates read own bookings"
  ON bookings FOR SELECT
  USING (auth.uid() = candidate_id);

DROP POLICY IF EXISTS "Mentors read own bookings" ON bookings;
CREATE POLICY "Mentors read own bookings"
  ON bookings FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM mentors m
    WHERE m.id = bookings.mentor_id AND m.profile_id = auth.uid()
  ));
