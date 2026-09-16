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

-- ---------------------------------------------------------------------
-- 034: IT Department + Full Stack Developer designation
-- ---------------------------------------------------------------------
-- Uses WHERE NOT EXISTS instead of ON CONFLICT so this doesn't depend
-- on department_name / designation_name / (leave_type_id, tier_name)
-- actually having a unique constraint in this database -- safe to
-- re-run either way.

-- 1. Department: IT
insert into departments (department_name, department_code)
select 'IT', 'IT'
where not exists (
    select 1 from departments where department_name = 'IT'
);

-- 2. Designation: Full Stack Developer, under the IT department
insert into designations (designation_name, department_id)
select 'Full Stack Developer', d.id
from departments d
where d.department_name = 'IT'
and not exists (
    select 1 from designations where designation_name = 'Full Stack Developer'
);

-- 3. Annual Leave "12 DAYS" tier (same as sql/033_*.sql -- repeated
--    here, safe to re-run, so this script alone is enough if 033
--    hasn't been applied yet). This is what gives the 12/12/12
--    Chennai leave policy its Annual Leave number; Sick/Casual = 12
--    comes from the "Chennai Leave Default" checkbox on the
--    Create/Edit User form.
insert into leave_policy_tiers (leave_type_id, tier_name, days)
select lt.id, '12 DAYS', 12
from leave_types lt
where lt.leave_name = 'ANNUAL LEAVE'
and not exists (
    select 1 from leave_policy_tiers
    where leave_type_id = lt.id and tier_name = '12 DAYS'
);


-- ---------------------------------------------------------------------
-- 033: Alternate Saturday schedule + Chennai Leave Default
-- ---------------------------------------------------------------------
-- Purely additive. Nothing here changes behaviour for existing
-- employees: alternate_saturday defaults to false (identical to today's
-- works_saturday Yes/No behaviour), and employee_leave_overrides only
-- affects an employee once a row exists for them.

-- 1. Alternate Saturday (works only the 1st & 3rd Saturday of the
--    month) -- a second, independent flag alongside works_saturday so
--    the existing Yes/No toggle and its logic are untouched. Only
--    meaningful when works_saturday = true; see
--    app/attendance/services.py _get_employee_shift.
alter table employees
    add column if not exists alternate_saturday boolean not null default false;


-- 2. Per-employee leave day overrides ("Chennai Leave Default": 12
--    Sick / 12 Casual). Used only for 'fixed' entitlement_mode leave
--    types (Sick Leave, Casual Leave). An employee with no row here
--    behaves exactly as before -- gets leave_types.default_days like
--    everyone else. See app/leaves/policy_services.py
--    _resolve_days_for_employee / get_my_leave_entitlements.
create table if not exists employee_leave_overrides (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid not null references employees(id) on delete cascade,
    leave_type_id uuid not null references leave_types(id) on delete cascade,
    days integer not null,
    created_at timestamp default now(),
    updated_at timestamp default now(),
    unique (employee_id, leave_type_id)
);

create index if not exists idx_employee_leave_overrides_employee
    on employee_leave_overrides(employee_id);


-- 3. Annual Leave "12 DAYS" tier -- fits into the existing tiered
--    Annual Leave mechanism (21/20/14/11/10) alongside it. HR picks
--    this from the same Annual Leave tier dropdown already on the
--    Create/Edit User form for Chennai employees; every other
--    department/location keeps using whichever tier they're on today.
--    WHERE NOT EXISTS instead of ON CONFLICT: doesn't depend on
--    (leave_type_id, tier_name) actually having a unique constraint in
--    this database -- safe to re-run either way.
insert into leave_policy_tiers (leave_type_id, tier_name, days)
select lt.id, '12 DAYS', 12
from leave_types lt
where lt.leave_name = 'ANNUAL LEAVE'
and not exists (
    select 1 from leave_policy_tiers
    where leave_type_id = lt.id and tier_name = '12 DAYS'
);


-- -- ---------------------------------------------------------------------
-- -- 033: Alternate Saturday schedule + Chennai Leave Default
-- -- ---------------------------------------------------------------------
-- -- Purely additive. Nothing here changes behaviour for existing
-- -- employees: alternate_saturday defaults to false (identical to today's
-- -- works_saturday Yes/No behaviour), and employee_leave_overrides only
-- -- affects an employee once a row exists for them.

-- -- 1. Alternate Saturday (works only the 1st & 3rd Saturday of the
-- --    month) -- a second, independent flag alongside works_saturday so
-- --    the existing Yes/No toggle and its logic are untouched. Only
-- --    meaningful when works_saturday = true; see
-- --    app/attendance/services.py _get_employee_shift.
-- alter table employees
--     add column if not exists alternate_saturday boolean not null default false;


-- -- 2. Per-employee leave day overrides ("Chennai Leave Default": 12
-- --    Sick / 12 Casual). Used only for 'fixed' entitlement_mode leave
-- --    types (Sick Leave, Casual Leave). An employee with no row here
-- --    behaves exactly as before -- gets leave_types.default_days like
-- --    everyone else. See app/leaves/policy_services.py
-- --    _resolve_days_for_employee / get_my_leave_entitlements.
-- create table if not exists employee_leave_overrides (
--     id uuid primary key default uuid_generate_v4(),
--     employee_id uuid not null references employees(id) on delete cascade,
--     leave_type_id uuid not null references leave_types(id) on delete cascade,
--     days integer not null,
--     created_at timestamp default now(),
--     updated_at timestamp default now(),
--     unique (employee_id, leave_type_id)
-- );

-- create index if not exists idx_employee_leave_overrides_employee
--     on employee_leave_overrides(employee_id);


-- -- 3. Annual Leave "12 DAYS" tier -- fits into the existing tiered
-- --    Annual Leave mechanism (21/20/14/11/10) alongside it. HR picks
-- --    this from the same Annual Leave tier dropdown already on the
-- --    Create/Edit User form for Chennai employees; every other
-- --    department/location keeps using whichever tier they're on today.
-- --    WHERE NOT EXISTS instead of ON CONFLICT: doesn't depend on
-- --    (leave_type_id, tier_name) actually having a unique constraint in
-- --    this database -- safe to re-run either way.
-- insert into leave_policy_tiers (leave_type_id, tier_name, days)
-- select lt.id, '12 DAYS', 12
-- from leave_types lt
-- where lt.leave_name = 'ANNUAL LEAVE'
-- and not exists (
--     select 1 from leave_policy_tiers
--     where leave_type_id = lt.id and tier_name = '12 DAYS'
-- );


-- =====================================================================
-- Akrobat HRMS — Site Visit "forgot to check out" flag
-- =====================================================================
-- Site visits can be closed two ways:
--   1. Employee explicitly taps "Departed Site" (depart_site), or arrives
--      at a new site which implicitly closes the previous one
--      (arrive_at_site) -- both are a real, deliberate action.
--   2. Employee checks out for the DAY (check_out) while a site visit is
--      still open -- this was already being auto-closed as a safety net
--      so it doesn't stay open forever, but with nothing recorded to say
--      it happened automatically vs. the employee actually departing.
--
-- This adds a flag + reason so the UI/reports can show "on progress"
-- visits that were auto-closed with a "forgot to check out" note,
-- without touching that note for visits the employee genuinely departed
-- from themselves.
-- =====================================================================
 
alter table attendance_site_visits
    add column if not exists auto_closed boolean not null default false;
 
alter table attendance_site_visits
    add column if not exists auto_close_reason text;