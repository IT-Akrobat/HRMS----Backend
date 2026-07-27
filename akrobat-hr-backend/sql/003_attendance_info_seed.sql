-- =====================================================================
-- Akrobat HRMS — company data seed from "Attendance Info.docx"
-- Run after 001_schema.sql and 002_role_permissions_seed.sql
-- =====================================================================
-- This migration adds the department / occupation / working-hours data
-- the company actually sent, which differs from the placeholder seed in
-- 001_schema.sql:
--   - 001_schema.sql's departments ("OPERATIONS", "SALES AND MARKETING",
--     "FINANCE" ...) were guesses made before this doc existed.
--   - This file inserts the real department names from the doc
--     ("QS", "INSPECTION", "DESIGN", "HR", "ACCOUNT", "OPERATION",
--     "PURCHASING & LOGISTICS", "SALES") and leaves the old rows in
--     place rather than renaming/deleting them, because employees or
--     designations may already reference the old department_id by FK.
--
-- Action needed before/после running in a live environment:
--   1. Decide whether to re-point any existing employees.department_id /
--      designations.department_id rows from the old placeholder
--      departments onto the new ones inserted here, then delete the
--      placeholders. A one-off UPDATE + DELETE, not included here,
--      since it depends on what's already been assigned in your data.
--   2. Everything below uses ON CONFLICT DO NOTHING (departments and
--      designations both have unique name constraints from
--      001_schema.sql), so this file is safe to re-run.
-- =====================================================================


-- =====================================
-- DEPARTMENTS (verbatim from the doc)
-- =====================================

insert into departments (department_name, department_code) values
('QS', 'QS'),
('INSPECTION', 'INSP'),
('DESIGN', 'DSGN'),
('HR', 'HR2'),
('ACCOUNT', 'ACCT'),
('OPERATION', 'OPRN'),
('PURCHASING & LOGISTICS', 'PLG'),
('SALES', 'SLS2')
on conflict (department_name) do nothing;


-- =====================================
-- DESIGNATIONS (mapped to the department names above)
-- =====================================

insert into designations (designation_name, department_id)
select v.designation_name, d.id
from (values
    ('QUANTITY SURVEYOR', 'QS'),
    ('SENIOR QUANTITY SURVEYOR CUM LOGISTICS', 'QS'),

    ('INSPECTION PLANNER', 'INSPECTION'),
    ('QUANTITY SURVEYOR (HEAD OF INSPECTION)', 'INSPECTION'),
    ('CONSTRUCTION WORKER', 'INSPECTION'),
    ('CONSTRUCTION WORKER-CUM-DRIVER', 'INSPECTION'),

    ('ENGINEER', 'DESIGN'),
    ('CIVIL ENGINEERING DRAFTER', 'DESIGN'),
    ('DESIGN ASSISTANT/DRAFTMAN', 'DESIGN'),

    ('ACCOUNTING PROGRAMMER', 'HR'),

    ('ACCOUNT EXECUTIVE', 'ACCOUNT'),

    ('PROJECT MANAGER', 'OPERATION'),
    ('CONSTRUCTION WORKER', 'OPERATION'),
    ('CONSTRUCTION WORKER-CUM-DRIVER', 'OPERATION'),
    ('DRIVER', 'OPERATION'),
    ('CONSTRUCTION WORKER (STOREMAN)', 'OPERATION'),

    ('PROCUREMENT AND LOGISTICS EXECUTIVE', 'PURCHASING & LOGISTICS'),

    ('ADMIN CUM SALES ASSISTANT', 'SALES')
) as v(designation_name, dept_code)
join departments d on d.department_name = v.dept_code
on conflict (designation_name) do nothing;

-- NOTE: "CONSTRUCTION WORKER" and "CONSTRUCTION WORKER-CUM-DRIVER" are
-- listed under both INSPECTION and OPERATION in the source doc, but
-- designations.designation_name is unique — a designation can only link
-- to one department in this schema. The rows above insert them under
-- INSPECTION first; the OPERATION inserts for the same names will be
-- skipped by ON CONFLICT DO NOTHING. If a given employee's designation
-- needs to reflect OPERATION instead, either add a second differently
-- named designation (e.g. "CONSTRUCTION WORKER (OPERATION)") or track
-- department at the employee level rather than the designation level
-- for these shared titles.


-- =====================================
-- SHIFTS (one row per area, since weekday/Saturday hours differ)
-- =====================================
-- working_hours / break_duration are in hours. Lunch break is 1 hour for
-- Office and Site per the doc; Saturday shifts have no listed lunch
-- break window so break_duration is 0 for those.

insert into shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status) values
('OFFICE - WEEKDAY (8:30-5:30)',  '08:30', '17:30', 8,   1, 10, 'Active'),
('OFFICE - WEEKDAY (9:00-6:00)',  '09:00', '18:00', 8,   1, 10, 'Active'),
('OFFICE - SATURDAY',             '08:30', '12:00', 3.5, 0, 10, 'Active'),

('OPERATION SITE - WEEKDAY',      '08:00', '16:30', 7.5, 1, 10, 'Active'),
('OPERATION SITE - SATURDAY',     '08:30', '15:30', 7,   0, 10, 'Active'),

('INSPECTION SITE - WEEKDAY',     '09:00', '18:00', 8,   1, 10, 'Active'),
('INSPECTION SITE - SATURDAY',    '09:00', '13:00', 4,   0, 10, 'Active'),

('WORK SHOP - WEEKDAY',           '06:30', '18:00', 10.5, 1, 10, 'Active'),
('WORK SHOP - SATURDAY',          '06:30', '17:00', 9.5,  0, 10, 'Active');

-- Everyone is off Sunday and public holidays — enforced at the
-- attendance/holiday-calendar level (see app/holidays), not on the
-- shift row itself, since shifts here only describe a working day's
-- hours.

-- Lunch window for Office weekdays is flexible (any 1 hour between
-- 11:30am and 2:00pm) rather than fixed, and Site lunch is fixed at
-- 12pm-1pm. The `shifts` table only stores a single break_duration
-- today, not a break window — if you need to enforce/report on the
-- *window* itself (e.g. flag an employee who took lunch outside
-- 11:30-2:00), that needs a new `lunch_window_start`/`lunch_window_end`
-- pair of columns on `shifts`, not just the duration already there:
--   alter table shifts add column lunch_window_start time;
--   alter table shifts add column lunch_window_end time;
-- Left out of this migration since it's a schema change, not seed data.
