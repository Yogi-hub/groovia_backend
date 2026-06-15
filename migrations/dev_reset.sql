-- dev_reset.sql
-- NOT part of the migration chain — run manually in a DEV/STAGING Supabase project's
-- SQL editor to wipe all user-generated data and restore the seed mentor directory.
-- Do NOT run this against production.

-- 1. Wipe auth users (cascades to profiles, mentors, consent_log, chat_threads via FKs).
delete from auth.users;

-- 2. Wipe everything else that isn't tied to auth.users via cascade.
truncate table webhook_events restart identity cascade;
truncate table bookings restart identity cascade;
truncate table mentors restart identity cascade;

-- 3. Wipe LangGraph checkpoint tables (created by PostgresSaver, may not exist yet).
do $$
begin
  if to_regclass('public.checkpoints') is not null then
    truncate table checkpoints, checkpoint_writes, checkpoint_blobs cascade;
  end if;
end $$;

-- 4. Re-seed the mentor directory.
\i 002_seed_mentors.sql
