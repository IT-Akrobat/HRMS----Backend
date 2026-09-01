-- =====================================================================
-- AD-HOC OUTDOOR / MEETING CHECK-IN
-- =====================================================================
-- Closes a gap the existing `employee_site_assignments` /
-- `attendance_site_visits` pair doesn't cover: those are for
-- Inspection/Operation field staff who are PRE-ASSIGNED to fixed sites
-- (see sql/014, sql/015). This is for the opposite case -- an
-- Account/HR/Logistics (or any office) employee who occasionally, and
-- unpredictably, has to go straight to a client meeting or site survey
-- instead of the office. There's no fixed site to assign in advance,
-- and -- per product discussion -- most employees never need this at
-- all, so it must NOT appear for every employee in a department the
-- moment this ships. It's gated per-employee, off by default.
-- =====================================================================


-- =====================================
-- 1. PER-EMPLOYEE FLAG
-- =====================================
-- Default false so this feature is invisible everywhere until HR/Admin
-- explicitly turns it on for a specific person via the existing
-- Employee edit screen (app/employees/services.py::update_employee
-- already passes any recognized column straight through -- see
-- app/employees/schemas.py EmployeeUpdate). Deliberately a boolean on
-- `employees`, not a role/department rule -- the same designation can
-- have some staff who need this "very rare" and others who never do.

alter table employees
    add column if not exists outdoor_checkin_enabled boolean not null default false;


-- =====================================
-- 2. AD-HOC OUTDOOR VISIT LOG
-- =====================================
-- Same "one row per stretch of time" shape as attendance_site_visits,
-- but with no location_id FK -- these places (a client's office, a
-- one-off site survey address) aren't in the `locations` master list,
-- so we capture raw GPS + a free-text purpose/address instead of
-- requiring a pre-configured location.

create table if not exists attendance_outdoor_visits (
    id uuid primary key default gen_random_uuid(),
    attendance_id uuid not null references attendance(id) on delete cascade,
    employee_id uuid not null references employees(id) on delete cascade,

    purpose text,              -- "Client meeting", "Site survey", etc.
    address_text text,         -- reverse-geocoded label, best-effort

    arrival_time timestamp not null,
    arrival_latitude double precision,
    arrival_longitude double precision,

    departure_time timestamp,
    departure_latitude double precision,
    departure_longitude double precision,

    duration_minutes integer,
    notes text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_outdoor_visits_employee_open
    on attendance_outdoor_visits(employee_id)
    where departure_time is null;

create index if not exists idx_outdoor_visits_attendance
    on attendance_outdoor_visits(attendance_id);


-- =====================================
-- 3. PERMISSION -- who can flip the flag
-- =====================================
-- Grants HR/Super Admin's existing role a way to toggle
-- outdoor_checkin_enabled without a new dedicated endpoint (it's just
-- another field on the Employee edit form, going through the normal
-- EDIT_EMPLOYEE-gated update_employee() path). No new permission row
-- is strictly required if EDIT_EMPLOYEE already covers it -- this is
-- here only if you want it separately auditable/toggleable from
-- EDIT_EMPLOYEE. Safe no-op if EDIT_EMPLOYEE already exists and you'd
-- rather reuse it; delete this block in that case.

insert into permissions (permission_name, module)
values ('MANAGE_OUTDOOR_CHECKIN', 'ATTENDANCE')
on conflict (permission_name) do nothing;