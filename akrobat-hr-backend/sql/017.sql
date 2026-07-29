-- =====================================
-- ACCESS CONTROL SETTINGS
-- =====================================
-- Singleton table (same pattern as `settings`, see 001_schema.sql) holding
-- the org-wide login security / password policy / lockout rules shown on
-- Super Admin > Security > Access Control.

create table access_control_settings (
    id uuid primary key default gen_random_uuid(),

    require_2fa boolean default false,
    session_timeout_minutes int default 60,

    password_min_length int default 8,
    password_require_complexity boolean default true,
    password_expiry_days int default 90,

    lockout_attempts int default 5,
    lockout_duration_minutes int default 15,

    restrict_to_office boolean default false,
    allowed_ip_ranges text[] default '{}',

    updated_at timestamptz default now()
);

insert into access_control_settings (id) values (gen_random_uuid());

-- =====================================
-- LOGIN LOCKOUT TRACKING
-- =====================================
-- One row per employee. Incremented on each failed sign-in attempt in
-- app/auth/services.py::login_user, reset on a successful sign-in.
-- Supabase Auth owns password verification itself (we never see the
-- password), so lockout has to be tracked on our side and checked
-- BEFORE handing the attempt to supabase.auth.sign_in_with_password.

create table login_lockouts (
    employee_id uuid primary key references employees(id) on delete cascade,
    failed_attempts int default 0,
    locked_until timestamptz,
    updated_at timestamptz default now()
);

-- MANAGE_ACCESS_CONTROL permission, so this can move from require_role
-- to require_permission later without another migration.
insert into permissions (permission_name, module)
values ('MANAGE_ACCESS_CONTROL', 'SETTINGS')
on conflict do nothing;