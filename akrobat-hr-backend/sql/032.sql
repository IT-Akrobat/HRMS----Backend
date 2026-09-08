-- =====================================================================
-- ATTENDANCE -- unique constraint on (employee_id, attendance_date)
-- =====================================================================
-- check_in() (app/attendance/services.py) currently guards against a
-- double check-in with a plain check-then-insert:
--
--     if attendance_repo.find_one({employee_id, attendance_date}):
--         bad_request("You have already checked in today.")
--     ...
--     attendance_repo.create(payload)
--
-- That's a classic TOCTOU race: two check-in requests for the same
-- employee arriving close enough together (a double-tap before the
-- button's disabled state re-renders, a mobile network retry, someone
-- checking in from two tabs/devices) can both read "no row yet" before
-- either one writes, and both then insert -- producing two attendance
-- rows for the same employee on the same day. Nothing in the schema
-- today stops that.
--
-- This is the actual fix: a unique constraint makes the DB itself the
-- single source of truth for "only one attendance row per employee per
-- day", no matter how many requests race each other or which app
-- server/worker handles them. check_in() has a matching code change to
-- catch the resulting unique-violation and turn it into the same
-- friendly "You have already checked in today." response instead of a
-- raw 500 -- see the unique-violation catch added around
-- attendance_repo.create(payload) there.
--
-- IMPORTANT -- run this check FIRST. If any employee already has more
-- than one attendance row for the same date (from a race that already
-- happened before this migration existed), the ALTER below will fail
-- until those duplicates are manually reviewed and merged/deleted:
--
--   select employee_id, attendance_date, count(*)
--   from attendance
--   group by employee_id, attendance_date
--   having count(*) > 1;
--
-- If that returns any rows, resolve them (decide which row is correct,
-- delete or merge the other(s)) before running the ALTER below.

alter table attendance
  add constraint attendance_employee_date_unique
  unique (employee_id, attendance_date);




--   -- =====================================================================
-- -- GEOCODE USAGE TRACKING -- hard cap on Google Geocoding API calls
-- -- =====================================================================
-- -- Google's Geocoding API has a free monthly allowance that resets every
-- -- calendar month, split into two separate quotas by Google's own pricing
-- -- (see app/locations/google_geocode_service.py):
-- --   - "google_india"  -- coordinates inside India:      70,000 free/mo
-- --   - "google_global" -- everywhere else (incl. Singapore): 10,000 free/mo
-- --
-- -- This table + function let the backend track calls against those
-- -- quotas and refuse to call Google once a (deliberately conservative)
-- -- threshold is hit -- at that point reverse-geocode requests just fall
-- -- back to OpenStreetMap/Nominatim (already the existing fallback, see
-- -- utils/Geocode.jsx) instead of ever going over into paid usage.
-- --
-- -- One row per (month, provider) -- e.g. ("2026-09", "google_india").
-- -- Safe to re-run.

-- create table if not exists geocode_usage (
--     id bigserial primary key,
--     month text not null,       -- "YYYY-MM", server-computed, UTC
--     provider text not null,    -- "google_india" | "google_global"
--     count integer not null default 0,
--     updated_at timestamptz not null default now(),
--     unique (month, provider)
-- );

-- -- Atomically increments the counter for (p_month, p_provider) and
-- -- returns the new count -- but ONLY if doing so would keep it strictly
-- -- under p_cap. If the row is already at/over the cap, the update is
-- -- skipped (via the WHERE clause on the ON CONFLICT DO UPDATE) and this
-- -- returns NULL instead -- callers treat NULL as "quota exhausted, don't
-- -- call Google this time."
-- --
-- -- This is a single atomic statement specifically so concurrent requests
-- -- (multiple check-ins landing at the same moment, multiple backend
-- -- worker processes) can't both read "count is fine" and both proceed,
-- -- overshooting the cap -- the same class of race condition already
-- -- fixed for double check-ins in 032.sql, just applied here to API spend
-- -- instead of attendance rows.
-- create or replace function increment_geocode_usage(
--     p_month text,
--     p_provider text,
--     p_cap integer
-- ) returns integer as $$
-- declare
--     new_count integer;
-- begin
--     insert into geocode_usage (month, provider, count)
--     values (p_month, p_provider, 1)
--     on conflict (month, provider)
--     do update set count = geocode_usage.count + 1, updated_at = now()
--     where geocode_usage.count < p_cap
--     returning count into new_count;

--     return new_count; -- NULL if the WHERE clause blocked the update
-- end;
-- $$ language plpgsql;