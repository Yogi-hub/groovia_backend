-- 001_init_slice0.sql
-- Slice 0 schema: profiles, mentors, chat_threads, consent_log
-- Run in: Supabase Dashboard → SQL Editor → New query → paste → Run

-- Safe re-run: drops the old dummy mentors table first
DROP TABLE IF EXISTS mentors CASCADE;

-- ============================================================================
-- Extensions
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- gen_random_uuid()

-- ============================================================================
-- Enums
-- ============================================================================
DO $$ BEGIN
  CREATE TYPE user_role AS ENUM ('candidate', 'mentor', 'admin');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
  CREATE TYPE mentor_status AS ENUM ('pending_review', 'approved', 'rejected', 'suspended');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================================
-- profiles — extends auth.users with platform-specific data
-- ============================================================================
CREATE TABLE IF NOT EXISTS profiles (
  id                      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  role                    user_role NOT NULL DEFAULT 'candidate',
  email                   TEXT UNIQUE NOT NULL,
  full_name               TEXT,
  display_name            TEXT,
  photo_url               TEXT,
  country_code            CHAR(2),                  -- ISO 3166-1 alpha-2
  city                    TEXT,
  timezone                TEXT DEFAULT 'UTC',
  target_country_code     CHAR(2),
  profession              TEXT,
  immigration_goal        TEXT,
  -- attribution (used by commission engine in Slice 3; added now to avoid migration later)
  attribution_source      TEXT,
  attribution_medium      TEXT,
  attribution_campaign    TEXT,
  attribution_mentor_id   UUID,
  attribution_locked_at   TIMESTAMPTZ,
  attribution_expires_at  TIMESTAMPTZ,
  -- credits (Slice 4)
  credit_balance          INTEGER NOT NULL DEFAULT 0 CHECK (credit_balance >= 0),
  email_notifications     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at              TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_profiles_role ON profiles(role) WHERE deleted_at IS NULL;

-- ============================================================================
-- mentors — public mentor profile (1:1 with profiles where role='mentor')
-- ============================================================================
CREATE TABLE IF NOT EXISTS mentors (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id               UUID UNIQUE REFERENCES profiles(id) ON DELETE CASCADE,  -- NULL for seeded demo mentors
  slug                     TEXT NOT NULL UNIQUE,
  display_name             TEXT NOT NULL,
  headline                 TEXT,
  bio                      TEXT,
  photo_url                TEXT,
  expertise_country_codes  CHAR(2)[] NOT NULL DEFAULT '{}',
  expertise_categories     TEXT[]    NOT NULL DEFAULT '{}',
  languages                TEXT[]    NOT NULL DEFAULT '{}',   -- ISO 639-1
  professional_domains     TEXT[]    NOT NULL DEFAULT '{}',
  years_lived_experience   INTEGER,
  linkedin_url             TEXT,
  youtube_url              TEXT,
  instagram_url            TEXT,
  booking_url              TEXT,
  status                   mentor_status NOT NULL DEFAULT 'approved',
  is_active                BOOLEAN NOT NULL DEFAULT TRUE,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mentors_status_active ON mentors(status, is_active);
CREATE INDEX IF NOT EXISTS idx_mentors_countries   ON mentors USING GIN (expertise_country_codes);
CREATE INDEX IF NOT EXISTS idx_mentors_categories  ON mentors USING GIN (expertise_categories);

-- ============================================================================
-- chat_threads — metadata wrapper around LangGraph thread_id
-- Messages themselves are stored by LangGraph's PostgresSaver in checkpoint tables.
-- ============================================================================
CREATE TABLE IF NOT EXISTS chat_threads (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID REFERENCES profiles(id) ON DELETE CASCADE,   -- NULL = guest thread
  title            TEXT,
  user_intent      TEXT,
  track            TEXT,
  last_message_at  TIMESTAMPTZ,
  message_count    INTEGER NOT NULL DEFAULT 0,
  is_archived      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_threads_user_recent
  ON chat_threads(user_id, last_message_at DESC NULLS LAST)
  WHERE is_archived = FALSE;

-- ============================================================================
-- consent_log — GDPR audit trail (append-only)
-- ============================================================================
CREATE TABLE IF NOT EXISTS consent_log (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  consent_type  TEXT NOT NULL,    -- 'tos', 'privacy', 'analytics_cookies', 'marketing_cookies'
  version       TEXT NOT NULL,
  ip_address    INET,
  user_agent    TEXT,
  granted_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_consent_log_user ON consent_log(user_id, consent_type);

-- ============================================================================
-- Trigger: auto-update updated_at on UPDATE
-- ============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles;
CREATE TRIGGER trg_profiles_updated_at
  BEFORE UPDATE ON profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_mentors_updated_at ON mentors;
CREATE TRIGGER trg_mentors_updated_at
  BEFORE UPDATE ON mentors
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_chat_threads_updated_at ON chat_threads;
CREATE TRIGGER trg_chat_threads_updated_at
  BEFORE UPDATE ON chat_threads
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ============================================================================
-- Trigger: auto-create profile row when a new auth.users row appears
-- Runs as SECURITY DEFINER so it can bypass RLS during the insert.
-- ============================================================================
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO profiles (id, email, full_name, photo_url, role)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(NEW.raw_user_meta_data->>'full_name', NEW.raw_user_meta_data->>'name'),
    NEW.raw_user_meta_data->>'avatar_url',
    'candidate'
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;

DROP TRIGGER IF EXISTS trg_on_auth_user_created ON auth.users;
CREATE TRIGGER trg_on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();

-- ============================================================================
-- Row Level Security policies
-- (Backend uses service_role key which bypasses RLS; frontend uses anon key.)
-- ============================================================================

-- profiles
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own profile" ON profiles;
CREATE POLICY "Users read own profile"
  ON profiles FOR SELECT
  USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users update own profile" ON profiles;
CREATE POLICY "Users update own profile"
  ON profiles FOR UPDATE
  USING (auth.uid() = id);

-- mentors
ALTER TABLE mentors ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Anyone reads approved active mentors" ON mentors;
CREATE POLICY "Anyone reads approved active mentors"
  ON mentors FOR SELECT
  USING (status = 'approved' AND is_active = TRUE);

DROP POLICY IF EXISTS "Mentor reads own row" ON mentors;
CREATE POLICY "Mentor reads own row"
  ON mentors FOR SELECT
  USING (auth.uid() = profile_id);

DROP POLICY IF EXISTS "Mentor updates own row" ON mentors;
CREATE POLICY "Mentor updates own row"
  ON mentors FOR UPDATE
  USING (auth.uid() = profile_id);

-- chat_threads
ALTER TABLE chat_threads ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users access own threads" ON chat_threads;
CREATE POLICY "Users access own threads"
  ON chat_threads FOR ALL
  USING (auth.uid() = user_id);

-- consent_log
ALTER TABLE consent_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Users read own consent" ON consent_log;
CREATE POLICY "Users read own consent"
  ON consent_log FOR SELECT
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users insert own consent" ON consent_log;
CREATE POLICY "Users insert own consent"
  ON consent_log FOR INSERT
  WITH CHECK (auth.uid() = user_id);
