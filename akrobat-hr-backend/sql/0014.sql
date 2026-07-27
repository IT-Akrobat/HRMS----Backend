-- =====================================================================
-- Akrobat HRMS — Site Visits + Designation Default Shifts
-- Run after 001_schema.sql, 002_role_permissions_seed.sql,
-- 003_attendance_info_seed.sql
-- =====================================================================
-- This is the migration app/attendance/services.py, app/employees/services.py
-- and app/core/helpers/employee_helper.py have been referring to in
-- comments (arrive_at_site / depart_site / resolve_default_shift_id) but
-- which never actually existed on disk — without it, "Arrived at Site" /
-- "Departed Site" errors out because `attendance_site_visits` doesn't
-- exist, and new employees never get a sensible default shift.
-- =====================================================================


-- =====================================
-- 1. SITE VISITS
-- =====================================
-- One row per "I'm at this site" stretch of a working day. A day with
-- 3 site visits = 3 rows sharing the same attendance_id. The parent
-- `attendance` row's check_in_time/check_out_time/working_minutes are
-- untouched by this — this table is purely an additive breakdown of
-- *where* the checked-in time was spent, for Inspection/Operation field
-- staff who move between sites in a single day.

create table if not exists attendance_site_visits (
    id uuid primary key default gen_random_uuid(),
    attendance_id uuid not null references attendance(id) on delete cascade,
    employee_id uuid not null references employees(id) on delete cascade,
    location_id uuid references locations(id) on delete set null,

    arrival_time timestamp not null,
    arrival_latitude double precision,
    arrival_longitude double precision,

    departure_time timestamp,
    departure_latitude double precision,
    departure_longitude double precision,

    duration_minutes integer,
    notes text,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_site_visits_attendance_id
    on attendance_site_visits(attendance_id);

create index if not exists idx_site_visits_employee_id
    on attendance_site_visits(employee_id);

-- Fast "who's currently at a site" lookups (departure_time is null while
-- the visit is open) — used by the manager "field staff live status" view.
create index if not exists idx_site_visits_open
    on attendance_site_visits(employee_id)
    where departure_time is null;


-- =====================================
-- 2. DESIGNATIONS.default_shift_id
-- =====================================
-- "When creating a user, their working hours should be mentioned" — HR
-- picks a designation, and the employee's shift defaults to whatever
-- that designation's area normally works (Office / Operation Site /
-- Inspection Site / Work Shop), per resolve_default_shift_id(). HR can
-- still override with a specific shift_id per employee.

alter table designations
    add column if not exists default_shift_id uuid references shifts(id) on delete set null;

-- Inspection-area designations -> Inspection Site weekday hours.
update designations d
set default_shift_id = s.id
from shifts s, departments dept
where d.department_id = dept.id
  and dept.department_name ilike 'INSPECTION%'
  and s.shift_name = 'INSPECTION SITE - WEEKDAY'
  and d.default_shift_id is null;

-- Operation-area designations -> Operation Site weekday hours.
update designations d
set default_shift_id = s.id
from shifts s, departments dept
where d.department_id = dept.id
  and dept.department_name ilike 'OPERATION%'
  and s.shift_name = 'OPERATION SITE - WEEKDAY'
  and d.default_shift_id is null;

-- Storeman is site-based but works Work Shop hours, not Operation Site
-- hours — narrower match runs after the broader OPERATION% one above so
-- it can override it.
update designations d
set default_shift_id = s.id
from shifts s
where d.designation_name ilike '%STOREMAN%'
  and s.shift_name = 'WORK SHOP - WEEKDAY';

-- Everything else (QS, Design, HR, Account, Purchasing & Logistics,
-- Sales, Admin, and any designation not under Inspection/Operation)
-- defaults to standard office hours.
update designations
set default_shift_id = (
    select id from shifts where shift_name = 'OFFICE - WEEKDAY (8:30-5:30)'
)
where default_shift_id is null;


-- =====================================
-- 3. NOTE: identifying "field staff" for dashboard purposes
-- =====================================
-- There's no single boolean column for "this employee works multiple
-- sites a day" — it's derived from department_id -> departments
-- .department_name being INSPECTION*/OPERATION* (see is_field_employee()
-- helper added in app/core/helpers/employee_helper.py). Kept this way
-- rather than adding a redundant flag, since department is already the
-- source of truth and the Inspection/Operation department set may grow
-- (e.g. a future "SURVEY" department) without a code change here.
