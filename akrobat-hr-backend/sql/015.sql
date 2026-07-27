-- =====================================================================
-- Akrobat HRMS — Employee Site Assignments
-- Run after 0014.sql (needs `locations`, `employees`, `roles`,
-- `permissions`, `role_permissions` already in place).
-- =====================================================================
-- Closes the gap between "here are all the company's sites" (locations
-- table) and "here is the ONE (or few) site(s) THIS employee is
-- actually meant to check in at". Before this, check-in and site-visit
-- arrival let an employee pick literally any configured location — this
-- adds a manager-driven assignment layer on top:
--
--   Manager assigns a location to a single employee, OR to their whole
--   team in one call (app/site_assignments/services.py) -> row(s) here.
--
--   Employee's check-in / site-visit "arrive" screens then only offer
--   (and the backend only accepts) a location_id the employee currently
--   has an active assignment for — see the `_get_active_assigned_location_ids`
--   guard added to app/attendance/services.py's check_in() and
--   arrive_at_site(). Employees with NO assignment row at all keep the
--   old "any location" behaviour, so this is additive, not breaking.
-- =====================================================================


-- =====================================
-- 1. TABLE
-- =====================================
-- One row per "employee is assigned to this site" stretch. An employee
-- can have more than one *active* row at once (field staff who legally
-- rotate between 2-3 assigned sites) — this is deliberately NOT a
-- single nullable `employees.assigned_site_id` column, so multi-site
-- field staff aren't a special case bolted on later.

create table if not exists employee_site_assignments (
    id uuid primary key default gen_random_uuid(),

    employee_id uuid not null references employees(id) on delete cascade,
    location_id uuid not null references locations(id) on delete cascade,

    assigned_by uuid references employees(id) on delete set null,

    assigned_from date not null default current_date,
    assigned_to date,

    is_active boolean not null default true,
    notes text,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create index if not exists idx_site_assignments_employee_id
    on employee_site_assignments(employee_id);

create index if not exists idx_site_assignments_location_id
    on employee_site_assignments(location_id);

-- Fast "what is this employee currently assigned to" lookups — the
-- exact query check_in()/arrive_at_site() run on every request.
create index if not exists idx_site_assignments_active
    on employee_site_assignments(employee_id)
    where is_active = true;

-- One employee can't be double-assigned to the exact same site twice
-- while both rows are active (re-assigning the same site is a no-op,
-- not a new row) — app/site_assignments/services.py also checks this
-- before insert, this is the DB-level backstop.
create unique index if not exists uq_site_assignments_active_pair
    on employee_site_assignments(employee_id, location_id)
    where is_active = true;


-- =====================================
-- 2. PERMISSIONS
-- =====================================
-- MANAGE_SITE_ASSIGNMENTS: create/update/deactivate assignments —
-- Managers and Team Leaders can only ever target their own direct/
-- indirect reports (enforced in the service layer via is_manager_of()),
-- HR/HR ADMIN/HR EXECUTIVE and SUPER ADMIN can target anyone.
-- VIEW_SITE_ASSIGNMENTS: read-only team/employee assignment views.
-- Reuses the 'ATTENDANCE' module so the existing "Attendance" sidebar
-- entry (already visible to these roles) doesn't need a new modules
-- table row just for this.

insert into permissions (permission_name, module)
values
    ('MANAGE_SITE_ASSIGNMENTS', 'ATTENDANCE'),
    ('VIEW_SITE_ASSIGNMENTS', 'ATTENDANCE')
on conflict (permission_name) do nothing;

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('MANAGER', 'TEAM LEADER', 'OPERATIONS MANAGER', 'HR ADMIN', 'HR EXECUTIVE')
  and p.permission_name in ('MANAGE_SITE_ASSIGNMENTS', 'VIEW_SITE_ASSIGNMENTS')
on conflict (role_id, permission_id) do nothing;

-- SUPER ADMIN already gets every permission implicitly (see
-- app/core/rbac.py) — no row needed for it here.
