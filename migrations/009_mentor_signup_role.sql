-- 009_mentor_signup_role.sql
-- The "Join as Mentor" signup passes role: 'mentor' in auth signup metadata.
-- Update the auto-profile-on-signup trigger to honor it (defaults to 'candidate' otherwise).
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
      NEW.raw_user_meta_data->>'avatar_url',
      NEW.raw_user_meta_data->>'picture'
    ),
    COALESCE(NEW.raw_user_meta_data->>'role', 'candidate')::user_role
  )
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public;
