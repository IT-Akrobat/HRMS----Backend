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



    -- =====================================================================
-- PERSISTENT "MISSED SITE VISIT" FLAG ON employee_site_assignments
-- =====================================================================
-- Until now, "did this employee miss their assigned site today" was
-- computed fresh every day by _get_missed_site_assignments() (app/
-- attendance/services.py) — purely by looking at whether an
-- attendance_site_visits row exists for today. That reset itself every
-- midnight: an employee who missed a visit yesterday got a brand-new,
-- fully-unlocked "Arrived" button again today, and the manager's
-- "Not visited" badge (GET /attendance/team/site-visit-status-today)
-- only ever reflected *today's* status.
--
-- Product decision: once a site visit is flagged missed, it should stay
-- flagged — the employee's "Arrived" button for that site stays locked,
-- and the manager keeps seeing the alert — until the manager takes an
-- explicit action on that assignment (reassigns the same or a
-- different site). This migration adds the two columns that make that
-- state persistent instead of recomputed-and-forgotten every day.
--
-- Safe to re-run: `add column if not exists`.
-- =====================================================================

alter table employee_site_assignments
    add column if not exists is_missed boolean not null default false;

alter table employee_site_assignments
    add column if not exists missed_since timestamptz;

-- Fast lookup for "which of my team's assignments are currently
-- flagged" (manager Team Members / Attendance pages).
create index if not exists idx_site_assignments_missed
    on employee_site_assignments(employee_id)
    where is_missed = true;


    -- Run once in Supabase -> SQL Editor
alter table employees add column if not exists username text;

-- One login username per employee, case-insensitive
create unique index if not exists employees_username_lower_uidx
  on employees (lower(username))
  where username is not null;

-- Example: give the installer his company login ID
-- update employees set username = 'sakthi'
--   where full_name ilike 'DETCHANAMURTHY SAKTHIVEL';



-- =====================================================================
-- OPERATION DEPARTMENT -- Saturday timing 8:00 AM - 3:30 PM, every Saturday
-- =====================================================================
-- Rule: everyone in the OPERATION department works EVERY Saturday
-- (no "Alternate Saturday / 1st & 3rd" pattern) from 8:00 AM to 3:30 PM.
--
-- 1. The Operation Saturday shift was 08:30-15:30 (sql/003). Change it to
--    08:00-15:30 = 7.5 working hours (no separate Saturday break).
-- 2. Backfill every existing Operation-department employee to
--    works_saturday = true / alternate_saturday = false so attendance
--    (late/overtime) and the monthly report treat every Saturday as a
--    working day for them.
--
-- Safe to re-run (idempotent).
-- =====================================================================

UPDATE shifts
SET start_time     = '08:00',
    end_time       = '15:30',
    working_hours  = 7.5,
    break_duration = 0
WHERE shift_name = 'OPERATION SITE - SATURDAY';

UPDATE employees e
SET works_saturday    = true,
    alternate_saturday = false
FROM departments d
WHERE e.department_id = d.id
  AND UPPER(TRIM(d.department_name)) LIKE 'OPERATION%'
  AND (e.works_saturday IS DISTINCT FROM true
       OR e.alternate_saturday IS DISTINCT FROM false);



       -- =====================================================================
-- OFFICE-HOURS STAFF -- choice of Saturday timing
-- =====================================================================
-- Staff on Office weekday hours (8:30-5:30 / 9:00-6:00) -- including an
-- Operation Project Manager with the MANAGER role -- can be given one of
-- two Saturday timings:
--     * 9:00 AM - 12:00 PM
--     * 8:30 AM - 12:30 PM
--
-- employees.saturday_shift_id stores the chosen one. Deliberately a plain
-- uuid with NO foreign key: a second employees -> shifts FK would make
-- every `shifts(...)` embed on employees ambiguous in PostgREST.
-- NULL = not chosen -> attendance falls back to the old single
-- "OFFICE - SATURDAY" (8:30-12:00) row, so nothing changes for existing
-- staff until HR picks one on the Edit User form.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE employees ADD COLUMN IF NOT EXISTS saturday_shift_id uuid;

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'OFFICE - SATURDAY (9:00-12:00)', '09:00', '12:00', 3, 0, 10, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'OFFICE - SATURDAY (9:00-12:00)');

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'OFFICE - SATURDAY (8:30-12:30)', '08:30', '12:30', 4, 0, 10, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'OFFICE - SATURDAY (8:30-12:30)');

-- =====================================================================
-- OPERATION DEPARTMENT -- Saturday timing 8:00 AM - 3:30 PM, every Saturday
-- =====================================================================
-- Rule: everyone in the OPERATION department works EVERY Saturday
-- (no "Alternate Saturday / 1st & 3rd" pattern) from 8:00 AM to 3:30 PM.
--
-- 1. The Operation Saturday shift was 08:30-15:30 (sql/003). Change it to
--    08:00-15:30 = 7.5 working hours (no separate Saturday break).
-- 2. Backfill every existing Operation-department employee to
--    works_saturday = true / alternate_saturday = false so attendance
--    (late/overtime) and the monthly report treat every Saturday as a
--    working day for them.
--
-- Safe to re-run (idempotent).
-- =====================================================================

UPDATE shifts
SET start_time     = '08:00',
    end_time       = '15:30',
    working_hours  = 7.5,
    break_duration = 0
WHERE shift_name = 'OPERATION SITE - SATURDAY';

-- Operation PROJECT MANAGER is excluded: they keep the Works Saturdays /
-- Alternate Saturday (1st & 3rd) options like other departments.
UPDATE employees e
SET works_saturday    = true,
    alternate_saturday = false
FROM departments d
LEFT JOIN designations des ON des.id = e.designation_id
WHERE e.department_id = d.id
  AND UPPER(TRIM(d.department_name)) LIKE 'OPERATION%'
  AND UPPER(COALESCE(des.designation_name, '')) NOT LIKE '%PROJECT MANAGER%'
  AND (e.works_saturday IS DISTINCT FROM true
       OR e.alternate_saturday IS DISTINCT FROM false);
       -- =====================================================================
-- INSPECTION TEAM -- choice of weekday timing
-- =====================================================================
-- Inspection staff can now be put on either:
--     * 8:00 AM - 4:30 PM
--     * 8:30 AM - 5:30 PM
-- (Create/Edit User form shows these as a dropdown.) The old single
-- "INSPECTION SITE - WEEKDAY" (9:00-6:00) row is kept so existing
-- employees on it keep working; nothing is changed for them until HR
-- picks a new timing on the Edit form. Saturday ("INSPECTION SITE -
-- SATURDAY") is unchanged.
--
-- 8.5h span - 1h lunch = 7.5 working hours for both.
-- Safe to re-run.
-- =====================================================================

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'INSPECTION SITE - WEEKDAY (8:00-4:30)', '08:00', '16:30', 7.5, 1, 10, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'INSPECTION SITE - WEEKDAY (8:00-4:30)');

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'INSPECTION SITE - WEEKDAY (8:30-5:30)', '08:30', '17:30', 7.5, 1, 10, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'INSPECTION SITE - WEEKDAY (8:30-5:30)');

-- New Inspection hires default to 8:30-5:30 (HR can pick 8:00-4:30).
UPDATE designations d
SET default_shift_id = (
    SELECT id FROM shifts WHERE shift_name = 'INSPECTION SITE - WEEKDAY (8:30-5:30)'
)
WHERE d.default_shift_id = (
    SELECT id FROM shifts WHERE shift_name = 'INSPECTION SITE - WEEKDAY'
);

-- =====================================================================
-- SATURDAY TIMING OPTIONS -- Inspection + Office (per Attendance_List sheet)
-- =====================================================================
-- Inspection staff can now pick a Saturday timing (employees.
-- saturday_shift_id, same column Office staff already use):
--     * 8:00 AM - 3:30 PM   (pairs with weekday 8:00-4:30)
--     * 8:30 AM - 12:30 PM  (pairs with weekday 8:30-5:30)
--     * 9:00 AM - 1:00 PM   (existing "INSPECTION SITE - SATURDAY",
--                            pairs with weekday 9:00-6:00)
-- Office staff get a third Saturday option: 8:30 AM - 12:00 PM.
--
-- grace_period is 0 on every new row (sql/022 zeroed it company-wide;
-- rows inserted later must not bring the 10-minute grace back).
-- Nothing changes for existing employees until HR picks a timing on the
-- Edit User form: NULL saturday_shift_id still falls back to the old
-- single "<AREA> - SATURDAY" row. Safe to re-run.
-- =====================================================================

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'INSPECTION SITE - SATURDAY (8:00-3:30)', '08:00', '15:30', 7.5, 0, 0, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'INSPECTION SITE - SATURDAY (8:00-3:30)');

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'INSPECTION SITE - SATURDAY (8:30-12:30)', '08:30', '12:30', 4, 0, 0, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'INSPECTION SITE - SATURDAY (8:30-12:30)');

INSERT INTO shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
SELECT 'OFFICE - SATURDAY (8:30-12:00)', '08:30', '12:00', 3.5, 0, 0, 'Active'
WHERE NOT EXISTS (SELECT 1 FROM shifts WHERE shift_name = 'OFFICE - SATURDAY (8:30-12:00)');

-- Re-zero grace on the rows sql/034 + sql/035 inserted with 10 minutes.
UPDATE shifts
SET grace_period = 0
WHERE shift_name IN (
    'OFFICE - SATURDAY (9:00-12:00)',
    'OFFICE - SATURDAY (8:30-12:30)',
    'INSPECTION SITE - WEEKDAY (8:00-4:30)',
    'INSPECTION SITE - WEEKDAY (8:30-5:30)'
) AND grace_period <> 0;


-- =====================================================================
-- EMPLOYEES -- "Working Location" (Office / Site / Office and Site)
-- =====================================================================
-- New field on Create User / Edit User. Separate from the existing
-- free-text employees.work_location (city/office name used for
-- timezone + holiday detection), which is left untouched.
--
-- NULL = not set (existing employees stay blank until HR fills it in).

alter table employees
    add column if not exists working_location text;

alter table employees
    drop constraint if exists employees_working_location_check;

alter table employees
    add constraint employees_working_location_check
    check (working_location is null
           or working_location in ('Office', 'Site', 'Office and Site'));


           -- =====================================================================
-- OT-eligible on-site staff (additional salary for overtime).
-- Run BEFORE deploying the matching backend change.
-- Safe to re-run.
-- =====================================================================

ALTER TABLE employees ADD COLUMN IF NOT EXISTS ot_eligible boolean NOT NULL DEFAULT false;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS ot_weekday_end time;   -- OT counts after this, Mon-Fri
ALTER TABLE employees ADD COLUMN IF NOT EXISTS ot_saturday_end time;  -- OT counts after this, Sat

-- GROUP 1: 8:00-16:30 Mon-Fri, 8:00-15:30 Sat
UPDATE employees
SET ot_eligible = true, ot_weekday_end = '16:30', ot_saturday_end = '15:30'
WHERE upper(trim(full_name)) IN (
  'DETCHANAMURTHY SAKTHIVEL',
  'MUTHUKKARUPPAN SINGARAVELU',
  'PANNEERSELVAM MURUGANANTHAM',
  'SELVANATHAN SATHISHKUMAR',
  'SELVARAJ ANANTH',
  'KANNAN SEEMAN',
  'MARIAPPAN ARJUNAN',
  'PANNEER SELVAM ANBU SELVAN',
  'ALAMIN 2 (RA)',
  'MADHAVAN CHELLAPANDIAN',
  'RAMALINGAM SRITHAR',
  'PERIYANNAN MARUTHU',
  'SELVARASU MAHESH',
  'RAJANKAM SENTHAMILAN',
  'VALLATHARASU GANESAMOORTHY',
  'ALAGAR AYYANJOTHI',
  'KARUNANITHI PRAVEEN KUMAR'
);

-- GROUP 2: 6:30-17:30 Mon-Fri, 6:30-16:30 Sat
UPDATE employees
SET ot_eligible = true, ot_weekday_end = '17:30', ot_saturday_end = '16:30'
WHERE upper(trim(full_name)) = 'ULAGANATHAN PRAKASH';

-- CHECK: should return 18 rows. If fewer, the missing names are spelled
-- differently in the employees table -- fix the spelling and re-run.
SELECT full_name, ot_weekday_end, ot_saturday_end FROM employees WHERE ot_eligible ORDER BY full_name;