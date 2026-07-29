-- Needed to actually enforce "Password expiry (days)" on Access Control.
-- Without a per-account timestamp of when the password was last set,
-- there's nothing to measure the expiry window against.

alter table user_profiles
    add column if not exists password_changed_at timestamptz default now();

-- Backfill: existing accounts get "changed today" rather than "changed at
-- the dawn of time", so turning expiry on doesn't immediately expire
-- every existing admin's password the moment this migration runs.
update user_profiles
set password_changed_at = now()
where password_changed_at is null;