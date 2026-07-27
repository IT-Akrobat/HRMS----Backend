-- =====================================================================
-- GET /auth/me + dynamic sidebar support
-- Run after 001-009.
-- =====================================================================
--
-- Two pieces of frontend-routing/sidebar behaviour were being decided
-- entirely by the Next.js app (a hardcoded switch on role name to pick
-- a redirect path, and a hardcoded per-role sidebar array). The brief
-- for /auth/me requires the backend to own both. This migration adds
-- the two small, data-driven pieces needed for that — a redirect path
-- per role, and a modules table the sidebar is generated from — instead
-- of hardcoding either list in Python.

-- =====================================
-- ROLES: post-login redirect path
-- =====================================

alter table roles add column if not exists redirect_path text;

update roles set redirect_path = '/super-admin' where role_name = 'SUPER ADMIN';
update roles set redirect_path = '/hr'          where role_name in ('HR ADMIN', 'HR EXECUTIVE');
update roles set redirect_path = '/manager'     where role_name in ('MANAGER', 'OPERATIONS MANAGER', 'INSPECTION MANAGER');
update roles set redirect_path = '/employee'    where role_name = 'EMPLOYEE';
update roles set redirect_path = '/viewer'      where role_name = 'VIEWER';

-- Any role added later (VENDOR, FINANCE, a CUSTOM_ROLE created through
-- the Roles admin screen, etc.) without an explicit redirect_path falls
-- back to '/employee' at the application layer (see app/auth/services.py)
-- rather than 404ing — but set one explicitly here whenever you add a
-- real role so it lands on its own area instead of the generic one:
--   update roles set redirect_path = '/vendor'  where role_name = 'VENDOR';
--   update roles set redirect_path = '/finance' where role_name = 'FINANCE';


-- =====================================
-- SIDEBAR MODULES
-- =====================================
-- One row per sidebar entry. `module_key` matches the `module` column
-- already used on `permissions` (e.g. 'EMPLOYEE', 'PAYROLL'), so a
-- user's sidebar is just: their role's distinct permission modules,
-- joined against this table for label/icon/route/order, plus whatever
-- is marked always_visible. Adding a new module to the sidebar is a
-- data change (insert a row + grant the matching permission to a role),
-- never a code change.

create table if not exists modules (
    id uuid primary key default uuid_generate_v4(),
    module_key text unique not null,
    label text not null,
    icon text not null,
    route text not null,
    sort_order integer not null default 100,
    always_visible boolean not null default false,
    created_at timestamp default now()
);

insert into modules (module_key, label, icon, route, sort_order, always_visible) values
    ('DASHBOARD',   'Dashboard',  'LayoutDashboard', '/dashboard',       0,  true),
    ('EMPLOYEE',    'Employees',  'Users',           '/employees',       10, false),
    ('ATTENDANCE',  'Attendance', 'Clock',            '/attendance',      20, false),
    ('LEAVE',       'Leave',      'CalendarDays',     '/leave',           30, false),
    ('OVERTIME',    'Overtime',   'Timer',            '/overtime',        40, false),
    ('PAYROLL',     'Payroll',    'Wallet',           '/payroll',         50, false),
    ('DOCUMENTS',   'Documents',  'FileText',         '/documents',       60, false),
    ('REPORTS',     'Reports',    'BarChart3',        '/reports',         70, false),
    ('AUDIT_LOGS',  'Audit',      'ShieldCheck',       '/audit',           80, false),
    ('SETTINGS',    'Settings',   'Settings',         '/settings',        90, false),
    ('PROFILE',     'Profile',    'UserCircle',       '/profile',         100, true)
on conflict (module_key) do nothing;

-- Note on scope: EMPLOYEE self-service items that don't map 1:1 to a
-- `permissions.module` value yet (e.g. "My Leave" vs the HR-facing
-- "Leave" module, "My Team") are a frontend-side relabeling of the same
-- backend module for now — see the sidebar-building note in
-- app/core/sidebar.py for how to split them later if the two views
-- genuinely need different routes.
