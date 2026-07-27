-- =====================================================================
-- Akrobat HRMS — consolidated schema
-- Assembled from the SQL previously provided (core, attendance/payroll,
-- performance, leave/overtime/projects/biometric/settings).
-- Run this before sql/002_role_permissions_seed.sql
-- =====================================================================

-- =====================================
-- EXTENSION
-- =====================================

create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;


-- =====================================
-- SYSTEM ROLES
-- =====================================

create table roles (
    id uuid primary key default uuid_generate_v4(),
    role_name text unique not null,
    description text,
    created_at timestamp default now()
);


-- =====================================
-- PERMISSIONS
-- =====================================

create table permissions (
    id uuid primary key default uuid_generate_v4(),
    permission_name text unique not null,
    module text,
    created_at timestamp default now()
);


-- =====================================
-- ROLE PERMISSION MAPPING
-- =====================================

create table role_permissions (
    id uuid primary key default uuid_generate_v4(),
    role_id uuid references roles(id) on delete cascade,
    permission_id uuid references permissions(id) on delete cascade,
    unique (role_id, permission_id)
);


-- =====================================
-- DEPARTMENTS
-- =====================================

create table departments (
    id uuid primary key default uuid_generate_v4(),
    department_name text unique not null,
    department_code text unique,
    manager_id uuid,
    status text default 'Active',
    created_at timestamp default now()
);


-- =====================================
-- DESIGNATIONS
-- =====================================

create table designations (
    id uuid primary key default uuid_generate_v4(),
    designation_name text unique not null,
    department_id uuid references departments(id) on delete set null,
    created_at timestamp default now()
);


-- =====================================
-- SHIFTS
-- =====================================

create table shifts (
    id uuid primary key default uuid_generate_v4(),
    shift_name text not null,
    start_time time,
    end_time time,
    working_hours numeric,
    break_duration numeric,
    grace_period numeric default 0,
    status text default 'Active',
    created_at timestamp default now()
);


-- =====================================
-- EMPLOYEES
-- =====================================

create table employees (
    id uuid primary key default uuid_generate_v4(),
    employee_id text unique not null,
    full_name text not null,
    email text unique,
    phone text,
    department_id uuid references departments(id) on delete set null,
    designation_id uuid references designations(id) on delete set null,
    manager_id uuid references employees(id) on delete set null,
    joining_date date,
    employment_status text default 'Active',
    work_location text,
    shift_id uuid references shifts(id) on delete set null,
    profile_photo text,
    created_at timestamp default now(),
    updated_at timestamp default now()
);

alter table departments
    add constraint departments_manager_id_fkey
    foreign key (manager_id) references employees(id) on delete set null;


-- =====================================
-- EMPLOYEE DOCUMENTS (legacy — superseded by `documents` below)
-- =====================================

create table employee_documents (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    document_name text,
    document_type text,
    file_url text,
    uploaded_at timestamp default now()
);


-- =====================================
-- USER PROFILE (Supabase Auth link)
-- =====================================

create table user_profiles (
    id uuid primary key default uuid_generate_v4(),
    auth_user_id uuid unique not null,
    employee_id uuid references employees(id) on delete cascade,
    role_id uuid references roles(id) on delete set null,
    is_active boolean default true,
    created_at timestamp default now()
);


-- =====================================
-- AUDIT LOGS (rich version — see note below)
-- =====================================

create table audit_logs (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid references employees(id),
    action text not null,
    module text not null,
    record_id uuid,
    description text,
    ip_address text,
    user_agent text,
    created_at timestamptz default now()
);
-- NOTE: app/core/audit.py currently packs old/new value diffs into the
-- `description` column as JSON text. If you'd rather have first-class
-- columns, add:
--   alter table audit_logs add column old_values jsonb;
--   alter table audit_logs add column new_values jsonb;
-- and update record_audit_log() in app/core/audit.py accordingly.


-- =====================================
-- SEED: SYSTEM ROLES
-- =====================================

insert into roles(role_name, description) values
('SUPER ADMIN','Full system access'),
('HR ADMIN','HR management access'),
('HR EXECUTIVE','Employee operations'),
('MANAGER','Team management'),
('OPERATIONS MANAGER','Project and workforce'),
('INSPECTION MANAGER','Inspection control'),
('EMPLOYEE','Employee self service'),
('VIEWER','Read only access');


-- =====================================
-- SEED: DESIGNATIONS
-- =====================================

insert into designations(designation_name) values
('DESIGN ASSISTANT/DRAFTMAN'),
('DRIVER CUM WELDER'),
('SALES AND MARKETING EXECUTIVE'),
('WORK-AT-HEIGHT INSPECTOR'),
('SENIOR QUANTITY SURVEYOR CUM LOGISTICS'),
('ADMINISTRATION CUM SALES ASSISTANT'),
('PROCUREMENT AND LOGISTICS EXECUTIVE'),
('PROJECT MANAGER'),
('INSPECTION PLANNER'),
('ACCOUNTS EXECUTIVE'),
('QUANTITY SURVEYOR'),
('CIVIL ENGINEERING DRAFTER'),
('ENGINEER'),
('CIVIL ENGINEER'),
('ACCOUNTING PROGRAMMER'),
('CONSTRUCTION WORKER'),
('CONSTRUCTION WORKER-CUM-DRIVER');


-- =====================================
-- SEED: PERMISSIONS
-- =====================================

insert into permissions(permission_name, module) values
('CREATE_EMPLOYEE','EMPLOYEE'),
('VIEW_EMPLOYEE','EMPLOYEE'),
('EDIT_EMPLOYEE','EMPLOYEE'),
('DELETE_EMPLOYEE','EMPLOYEE'),
('VIEW_ATTENDANCE','ATTENDANCE'),
('EDIT_ATTENDANCE','ATTENDANCE'),
('APPROVE_LEAVE','LEAVE'),
('APPROVE_OVERTIME','OVERTIME'),
('VIEW_REPORTS','REPORTS'),
('MANAGE_SETTINGS','SETTINGS');


-- =====================================
-- SEED: DEPARTMENTS
-- =====================================

insert into departments(department_name, department_code) values
('HUMAN RESOURCE','HR'),
('FINANCE','FIN'),
('OPERATIONS','OPS'),
('INSPECTION','INS'),
('SALES AND MARKETING','SALES'),
('PROCUREMENT AND LOGISTICS','PL'),
('ADMINISTRATION','ADMIN'),
('ENGINEERING','ENG'),
('CONSTRUCTION','CON');


-- =====================================================================
-- ATTENDANCE SYSTEM
-- =====================================================================

create table attendance (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    attendance_date date not null,
    check_in_time timestamp,
    check_out_time timestamp,
    break_minutes integer default 0,
    working_minutes integer default 0,
    late_minutes integer default 0,
    early_checkout_minutes integer default 0,
    overtime_minutes integer default 0,
    status text default 'Present',
    created_at timestamp default now(),
    updated_at timestamp default now()
);

create table attendance_breaks (
    id uuid primary key default uuid_generate_v4(),
    attendance_id uuid references attendance(id) on delete cascade,
    break_start timestamp,
    break_end timestamp,
    break_minutes integer default 0,
    created_at timestamp default now()
);

create table attendance_corrections (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    attendance_id uuid references attendance(id) on delete cascade,
    requested_check_in timestamp,
    requested_check_out timestamp,
    reason text,
    status text default 'Pending',
    approved_by uuid references employees(id),
    created_at timestamp default now()
);

create table attendance_rules (
    id uuid primary key default uuid_generate_v4(),
    rule_name text not null,
    late_grace_minutes integer default 0,
    minimum_work_minutes integer,
    overtime_after_minutes integer,
    created_at timestamp default now()
);

create table employee_shift_history (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    shift_id uuid references shifts(id) on delete cascade,
    effective_from date,
    effective_to date,
    created_at timestamp default now()
);

insert into attendance_rules (rule_name, late_grace_minutes, minimum_work_minutes, overtime_after_minutes)
values ('Default Company Rule', 10, 480, 480);

create table locations (
    id uuid primary key default gen_random_uuid(),
    location_name text not null,
    location_code text unique,
    address text,
    latitude double precision,
    longitude double precision,
    radius integer,
    created_at timestamptz default now()
);


-- =====================================================================
-- PROJECTS (created before payroll/documents/assignments that reference it)
-- =====================================================================

create table projects (
    id uuid primary key default uuid_generate_v4(),
    project_code text unique,
    project_name text not null,
    description text,
    client_name text,
    project_location text,
    start_date date,
    end_date date,
    status text default 'Planning',
    progress_percentage integer default 0,
    project_manager_id uuid references employees(id) on delete set null,
    created_at timestamp default now(),
    updated_at timestamp default now()
);

create table project_assignments (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references projects(id) on delete cascade,
    employee_id uuid references employees(id) on delete cascade,
    assigned_role text,
    allocation_percentage integer default 100,
    assigned_date date,
    released_date date,
    status text default 'Active',
    created_at timestamp default now()
);

create table project_workload (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references projects(id) on delete cascade,
    employee_id uuid references employees(id) on delete cascade,
    planned_hours numeric default 0,
    actual_hours numeric default 0,
    updated_at timestamp default now()
);

create table project_status_history (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references projects(id) on delete cascade,
    old_status text,
    new_status text,
    changed_by uuid references employees(id),
    remarks text,
    changed_at timestamp default now()
);

create table project_locations (
    id uuid primary key default uuid_generate_v4(),
    project_id uuid references projects(id) on delete cascade,
    location_name text,
    latitude numeric,
    longitude numeric,
    radius_meter integer default 100,
    created_at timestamp default now()
);


-- =====================================================================
-- PAYROLL / DOCUMENTS / SETTINGS / EXPENSES
-- =====================================================================

create table payroll (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    payroll_month integer not null,
    payroll_year integer not null,
    basic_salary numeric(12,2) not null,
    allowance numeric(12,2) default 0,
    overtime_amount numeric(12,2) default 0,
    bonus numeric(12,2) default 0,
    deduction numeric(12,2) default 0,
    leave_deduction numeric(12,2) default 0,
    tax numeric(12,2) default 0,
    net_salary numeric(12,2) not null,
    payment_status text default 'PENDING',
    payment_date date,
    remarks text,
    created_at timestamptz default now(),
    updated_at timestamptz default now(),
    unique(employee_id, payroll_month, payroll_year)
);

create table documents (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    document_name text not null,
    document_type text not null,
    file_url text not null,
    expiry_date date,
    remarks text,
    created_at timestamptz default now()
);

create table employee_project_assignments (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    project_id uuid not null references projects(id) on delete cascade,
    assigned_from date not null,
    assigned_to date,
    is_active boolean default true,
    remarks text,
    created_at timestamptz default now()
);

create table settings (
    id uuid primary key default gen_random_uuid(),
    company_name text,
    company_email text,
    company_phone text,
    company_address text,
    company_logo text,
    office_start_time time,
    office_end_time time,
    default_shift_id uuid references shifts(id),
    currency text default 'SGD',
    timezone text default 'Asia/Singapore',
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table expenses (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete cascade,
    expense_date date not null,
    category text not null,
    amount numeric(10,2) not null,
    description text,
    receipt_url text,
    status text default 'PENDING',
    approved_by uuid references employees(id),
    approved_at timestamptz,
    remarks text,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);


-- =====================================================================
-- PERFORMANCE MANAGEMENT
-- =====================================================================

create table performance_reviews (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    reviewer_id uuid references employees(id) on delete set null,
    review_period text,
    review_date date,
    attendance_score numeric default 0,
    productivity_score numeric default 0,
    quality_score numeric default 0,
    teamwork_score numeric default 0,
    discipline_score numeric default 0,
    overall_score numeric default 0,
    rating text,       -- EXCELLENT / GOOD / AVERAGE / NEEDS IMPROVEMENT
    feedback text,
    status text default 'Draft',   -- DRAFT / SUBMITTED / APPROVED
    created_at timestamp default now(),
    updated_at timestamp default now()
);

create table employee_goals (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    goal_title text,
    goal_description text,
    target_date date,
    completion_percentage integer default 0,
    status text default 'Active',
    created_at timestamp default now()
);

create table notifications (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid,
    title text,
    message text,
    notification_type text,   -- LEAVE / OVERTIME / ATTENDANCE / SYSTEM
    is_read boolean default false,
    created_at timestamp default now()
);

create table announcements (
    id uuid primary key default uuid_generate_v4(),
    title text not null,
    message text,
    created_by uuid references employees(id) on delete set null,
    target_type text,   -- ALL / DEPARTMENT / ROLE
    target_id uuid,
    start_date date,
    end_date date,
    status text default 'Active',
    created_at timestamp default now()
);

create table employee_activity_logs (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    activity_type text,   -- LOGIN / PROFILE_UPDATE / DOCUMENT_UPLOAD / ATTENDANCE
    description text,
    created_at timestamp default now()
);

create table performance_templates (
    id uuid primary key default uuid_generate_v4(),
    template_name text,
    attendance_weight numeric default 20,
    productivity_weight numeric default 30,
    quality_weight numeric default 25,
    teamwork_weight numeric default 15,
    discipline_weight numeric default 10,
    created_at timestamp default now()
);

insert into performance_templates
(template_name, attendance_weight, productivity_weight, quality_weight, teamwork_weight, discipline_weight)
values ('Default Employee Evaluation', 20, 30, 25, 15, 10);

create table employee_emergency_contacts (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    contact_name text not null,
    relationship text,
    phone text,
    address text,
    created_at timestamp default now()
);

create table employee_education (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    institution_name text,
    qualification text,
    specialization text,
    start_year integer,
    end_year integer,
    created_at timestamp default now()
);

create table employee_experience (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    company_name text,
    designation text,
    start_date date,
    end_date date,
    responsibilities text,
    created_at timestamp default now()
);


-- =====================================================================
-- LEAVE MANAGEMENT
-- =====================================================================

create table leave_types (
    id uuid primary key default uuid_generate_v4(),
    leave_name text unique not null,
    description text,
    default_days integer default 0,
    created_at timestamp default now()
);

create table leave_balances (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    leave_type_id uuid references leave_types(id) on delete cascade,
    total_days integer default 0,
    used_days integer default 0,
    remaining_days integer default 0,
    year integer,
    created_at timestamp default now(),
    updated_at timestamp default now(),
    unique(employee_id, leave_type_id, year)
);

create table leave_requests (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    leave_type_id uuid references leave_types(id) on delete cascade,
    start_date date not null,
    end_date date not null,
    total_days integer,
    reason text,
    status text default 'Pending',
    applied_date timestamp default now(),
    approved_by uuid references employees(id),
    approved_date timestamp
);

create table leave_approval_history (
    id uuid primary key default uuid_generate_v4(),
    leave_request_id uuid references leave_requests(id) on delete cascade,
    action text,
    action_by uuid references employees(id),
    comments text,
    action_date timestamp default now()
);

create table holidays (
    id uuid primary key default uuid_generate_v4(),
    holiday_name text,
    holiday_date date,
    description text,
    created_at timestamp default now()
);

insert into leave_types (leave_name, description, default_days) values
('CASUAL LEAVE','Personal leave',12),
('SICK LEAVE','Medical leave',14),
('ANNUAL LEAVE','Yearly paid leave',18),
('UNPAID LEAVE','Without salary',0),
('EMERGENCY LEAVE','Emergency situations',5);


-- =====================================================================
-- OVERTIME MANAGEMENT
-- =====================================================================

create table overtime_requests (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    overtime_date date not null,
    requested_hours numeric,
    approved_hours numeric default 0,
    actual_hours numeric default 0,
    reason text,
    status text default 'Pending',
    submitted_at timestamp default now(),
    approved_by uuid references employees(id),
    approved_at timestamp
);

create table overtime_approval_history (
    id uuid primary key default uuid_generate_v4(),
    overtime_request_id uuid references overtime_requests(id) on delete cascade,
    action text,
    action_by uuid references employees(id),
    comments text,
    action_date timestamp default now()
);

create table overtime_rules (
    id uuid primary key default uuid_generate_v4(),
    rule_name text,
    max_daily_ot_hours numeric,
    max_monthly_ot_hours numeric,
    created_at timestamp default now()
);

create table overtime_summary (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    month integer,
    year integer,
    total_requested_hours numeric default 0,
    total_approved_hours numeric default 0,
    total_actual_hours numeric default 0,
    created_at timestamp default now(),
    unique(employee_id, month, year)
);

insert into overtime_rules (rule_name, max_daily_ot_hours, max_monthly_ot_hours)
values ('Company OT Rule', 4, 60);


-- =====================================================================
-- BIOMETRIC ATTENDANCE
-- =====================================================================

create table attendance_devices (
    id uuid primary key default uuid_generate_v4(),
    device_name text not null,
    device_type text not null,   -- FINGERPRINT / FACE_RECOGNITION
    device_serial_number text unique,
    location_name text,
    status text default 'Active',
    created_at timestamp default now()
);

create table employee_biometrics (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    biometric_type text not null,   -- FINGERPRINT / FACE
    biometric_device_id text not null,
    registered_date timestamp default now(),
    status text default 'Active'
);

create table biometric_logs (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid references employees(id) on delete cascade,
    device_id uuid references attendance_devices(id) on delete set null,
    biometric_type text,   -- FINGERPRINT / FACE
    punch_type text,       -- CHECK_IN / CHECK_OUT
    punch_time timestamp not null,
    created_at timestamp default now()
);

alter table attendance add column device_id uuid references attendance_devices(id) on delete set null;
alter table attendance add column attendance_source text default 'BIOMETRIC';

create table biometric_sync_logs (
    id uuid primary key default uuid_generate_v4(),
    device_id uuid references attendance_devices(id) on delete cascade,
    sync_start_time timestamp,
    sync_end_time timestamp,
    records_received integer default 0,
    sync_status text,
    error_message text,
    created_at timestamp default now()
);

create table biometric_device_tokens (
    id uuid primary key default uuid_generate_v4(),
    device_id uuid references attendance_devices(id) on delete cascade,
    api_token text unique,
    is_active boolean default true,
    created_at timestamp default now()
);

insert into attendance_devices (device_name, device_type, device_serial_number, location_name) values
('Main Office Fingerprint Machine','FINGERPRINT','FP-001','Office'),
('Main Office Face Scanner','FACE_RECOGNITION','FACE-001','Office');


-- =====================================================================
-- SYSTEM SETTINGS
-- =====================================================================

create table company_settings (
    id uuid primary key default uuid_generate_v4(),
    company_name text,
    company_email text,
    company_phone text,
    company_address text,
    logo_url text,
    created_at timestamp default now(),
    updated_at timestamp default now()
);

create table company_locations (
    id uuid primary key default uuid_generate_v4(),
    location_name text not null,
    location_type text,   -- OFFICE / BRANCH / PROJECT_SITE
    address text,
    city text,
    country text,
    status text default 'Active',
    created_at timestamp default now()
);

create table employment_types (
    id uuid primary key default uuid_generate_v4(),
    type_name text unique,   -- FULL_TIME / PART_TIME / CONTRACT / TEMPORARY
    created_at timestamp default now()
);

create table working_days (
    id uuid primary key default uuid_generate_v4(),
    day_name text,
    is_working_day boolean default true,
    created_at timestamp default now()
);

create table company_holidays (
    id uuid primary key default uuid_generate_v4(),
    holiday_name text,
    holiday_date date,
    description text,
    created_at timestamp default now()
);

create table document_types (
    id uuid primary key default uuid_generate_v4(),
    document_name text unique,   -- ID CARD / PASSPORT / CERTIFICATE / CONTRACT
    mandatory boolean default false,
    created_at timestamp default now()
);

create table system_settings (
    id uuid primary key default uuid_generate_v4(),
    setting_key text unique,
    setting_value text,
    description text,
    created_at timestamp default now(),
    updated_at timestamp default now()
);

insert into employment_types(type_name) values
('FULL_TIME'),('PART_TIME'),('CONTRACT'),('TEMPORARY');

insert into working_days(day_name, is_working_day) values
('MONDAY',true),('TUESDAY',true),('WEDNESDAY',true),
('THURSDAY',true),('FRIDAY',true),('SATURDAY',false),('SUNDAY',false);
