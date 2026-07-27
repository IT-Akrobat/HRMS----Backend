-- =====================================================================
-- TEAM LEADER role + Department/Designation alignment
-- Run after 001-010.
-- =====================================================================
--
-- Two gaps this closes:
--
-- 1. There is no 'TEAM LEADER' (TL) role yet — Owner/Super Admin needs
--    to be able to create one (sits between MANAGER and EMPLOYEE).
--
-- 2. `designations.department_id` was left NULL by the very first seed
--    (sql/001_schema.sql inserted designation_name only) — so
--    designations exist but aren't actually linked to a department.
--    This backfills that link, and adds the handful of
--    department/designation combinations from the org chart doc that
--    didn't exist yet at all.
--
-- Fixed (hand-picked, not uuid_generate_v4()) ids are used for every
-- *new* row here so the Swagger sample payloads that reference them
-- stay valid no matter which environment this runs against. Rows that
-- already existed before this migration keep whatever id they already
-- have — fetch those via GET /roles, GET /departments, GET /designations.

-- =====================================
-- 1. TEAM LEADER ROLE
-- =====================================

insert into roles (id, role_name, description, redirect_path)
values (
    '11111111-1111-1111-1111-111111111111',
    'TEAM LEADER',
    'Leads a small team under a Manager; day-to-day team/attendance oversight',
    '/manager' -- reuses the Manager frontend area for now; give it its own
               -- route (e.g. /team-lead) once the frontend has a dedicated area
)
on conflict (role_name) do nothing;

-- Starting permission set for TL — team visibility + attendance
-- correction approvals, but NOT leave/overtime approval (still a
-- Manager-level call). Tune freely via role_permissions later; nothing
-- about this is hardcoded elsewhere in the app.
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'TEAM LEADER'
  and p.permission_name in (
    'VIEW_EMPLOYEE', 'VIEW_ATTENDANCE', 'APPROVE_ATTENDANCE_CORRECTION'
  )
on conflict (role_id, permission_id) do nothing;

-- =====================================
-- 2. NEW DEPARTMENT: QS (Quantity Surveying)
-- =====================================
-- Doc lists "QS Department" separately from Inspection/Operations.

insert into departments (id, department_name, department_code)
values (
    '22222222-2222-2222-2222-222222222222',
    'QUANTITY SURVEYING',
    'QS'
)
on conflict (department_name) do nothing;

-- =====================================
-- 3. BACKFILL department_id ON EXISTING DESIGNATIONS
-- =====================================
-- Mapping straight from the org chart doc. Departments referenced here
-- (INSPECTION, ENGINEERING, HUMAN RESOURCE, FINANCE, OPERATIONS,
-- PROCUREMENT AND LOGISTICS, SALES AND MARKETING) already exist from
-- sql/001_schema.sql — only QUANTITY SURVEYING above is new.
--
-- Note: doc says "Design Department" / "Account Department" — mapped to
-- the closest existing department names (ENGINEERING / FINANCE) rather
-- than creating near-duplicates. Rename those departments instead if
-- you want the exact doc wording to show up in the UI.

update designations set department_id = (select id from departments where department_name = 'QUANTITY SURVEYING')
where designation_name = 'SENIOR QUANTITY SURVEYOR CUM LOGISTICS';

update designations set department_id = (select id from departments where department_name = 'QUANTITY SURVEYING')
where designation_name = 'QUANTITY SURVEYOR';

update designations set department_id = (select id from departments where department_name = 'INSPECTION')
where designation_name in ('INSPECTION PLANNER', 'CONSTRUCTION WORKER', 'CONSTRUCTION WORKER-CUM-DRIVER');

update designations set department_id = (select id from departments where department_name = 'ENGINEERING')
where designation_name in ('ENGINEER', 'CIVIL ENGINEERING DRAFTER', 'DESIGN ASSISTANT/DRAFTMAN', 'CIVIL ENGINEER');

update designations set department_id = (select id from departments where department_name = 'HUMAN RESOURCE')
where designation_name = 'ACCOUNTING PROGRAMMER';

update designations set department_id = (select id from departments where department_name = 'FINANCE')
where designation_name = 'ACCOUNTS EXECUTIVE';

update designations set department_id = (select id from departments where department_name = 'OPERATIONS')
where designation_name = 'PROJECT MANAGER';

update designations set department_id = (select id from departments where department_name = 'PROCUREMENT AND LOGISTICS')
where designation_name = 'PROCUREMENT AND LOGISTICS EXECUTIVE';

update designations set department_id = (select id from departments where department_name = 'SALES AND MARKETING')
where designation_name in ('ADMINISTRATION CUM SALES ASSISTANT', 'SALES AND MARKETING EXECUTIVE');

update designations set department_id = (select id from departments where department_name = 'ADMINISTRATION')
where designation_name = 'WORK-AT-HEIGHT INSPECTOR';

update designations set department_id = (select id from departments where department_name = 'OPERATIONS')
where designation_name = 'DRIVER CUM WELDER';

-- =====================================
-- 4. NEW DESIGNATIONS (from the doc, didn't exist at all before)
-- =====================================

insert into designations (id, designation_name, department_id) values
    ('33333333-3333-3333-3333-333333333333', 'QUANTITY SURVEYOR (HEAD OF INSPECTION)',
        (select id from departments where department_name = 'INSPECTION')),
    ('33333333-3333-3333-3333-333333333334', 'CONSTRUCTION WORKER (STOREMAN)',
        (select id from departments where department_name = 'OPERATIONS')),
    ('33333333-3333-3333-3333-333333333335', 'DRIVER',
        (select id from departments where department_name = 'OPERATIONS'))
on conflict (designation_name) do nothing;
