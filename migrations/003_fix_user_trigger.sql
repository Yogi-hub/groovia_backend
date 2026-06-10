-- 003_fix_user_trigger.sql
-- Google OAuth puts the avatar URL in `picture`, not `avatar_url`.
-- This patch updates the auto-profile-on-signup trigger to handle both.
-- Safe to re-run — CREATE OR REPLACE FUNCTION is idempotent.

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO profiles (id, email, full_name, photo_url, role)
  VALUES (
    NEW.id,
    NEW.email,
    COALESCE(
      NEW.raw_user_meta_data->>'full_name',
      NEW.raw_user_meta_data->>'name'
    ),
    COALESCE(
      NEW.raw_user_meta_data->>'avatar_url',  -- GitHub, Discord, etc.
      NEW.raw_user_meta_data->>'picture'      -- Google
    ),
    'candidate'
  )
  ON CONFLICT (id) DO NOTHING;  -- safety against re-fires
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;
