-- =====================================================================
-- LEAVE POLICY ENGINE
-- =====================================================================
-- Implements the Singapore leave policy from
-- "Leave_info_for_Attendance_App.xlsx": tiered entitlements (Annual,
-- Childcare), eligibility rules driven off employee personal fields
-- (nationality / marital_status / gender / office-vs-field), event-based
-- leave that has no fixed yearly balance (NS Leave, Replacement Leave),
-- and leave types that never touch leave_balances at all (Unpaid Leave).
--
-- Safe to re-run: every DDL statement below uses IF NOT EXISTS /
-- ON CONFLICT DO NOTHING.

-- ---------------------------------------------------------------------
-- 0. Employee personal-detail columns
-- ---------------------------------------------------------------------
-- app/employees/schemas.py (EmployeeSelfUpdate) and app/auth/services.py
-- have read/written employees.gender / marital_status / nationality /
-- blood_group / religion / address since the profile self-update
-- feature shipped, but no prior migration actually added these columns
-- to the `employees` table — every write to them has been silently
-- swallowed by Supabase/PostgREST. Adding them here is a prerequisite
-- for the eligibility engine below, which reads nationality,
-- marital_status and gender directly off `employees`.

alter table employees add column if not exists gender text;
alter table employees add column if not exists marital_status text;
alter table employees add column if not exists nationality text;
alter table employees add column if not exists blood_group text;
alter table employees add column if not exists religion text;
alter table employees add column if not exists address text;

-- Working days/week — drives the Unpaid Leave payroll deduction
-- (Unpaid Leave never gets a leave_balances row; payroll reads this
-- column directly). 5 / 5.5 / 6 per the Leave Info doc.
alter table employees add column if not exists working_days_per_week numeric(3,1) default 5;
alter table employees add constraint employees_working_days_per_week_check
    check (working_days_per_week in (5, 5.5, 6))
    not valid;
-- NOT VALID so existing rows (all default 5, which satisfies it anyway)
-- don't block the migration; validate separately once data is clean:
--   alter table employees validate constraint employees_working_days_per_week_check;

-- ---------------------------------------------------------------------
-- 1. leave_types: entitlement_mode + is_paid
-- ---------------------------------------------------------------------

alter table leave_types add column if not exists entitlement_mode text;
alter table leave_types add column if not exists is_paid boolean not null default true;

alter table leave_types
    add constraint leave_types_entitlement_mode_check
    check (entitlement_mode in ('fixed', 'tiered', 'event', 'not_a_balance'))
    not valid;

-- Classify the leave types already seeded in 001_schema.sql.
update leave_types set entitlement_mode = 'fixed'   where leave_name = 'SICK LEAVE';
update leave_types set entitlement_mode = 'not_a_balance', is_paid = false
    where leave_name = 'UNPAID LEAVE';
update leave_types set entitlement_mode = 'tiered'  where leave_name = 'ANNUAL LEAVE';
-- CASUAL LEAVE / EMERGENCY LEAVE aren't in the Leave Info doc at all;
-- leave them as plain fixed-balance types rather than guessing at
-- eligibility rules for them.
update leave_types set entitlement_mode = 'fixed'
    where leave_name in ('CASUAL LEAVE', 'EMERGENCY LEAVE')
    and entitlement_mode is null;

-- New leave types from the Leave Info doc that didn't exist before.
insert into leave_types (leave_name, description, default_days, entitlement_mode, is_paid)
values
    ('HOSPITALISATION LEAVE', 'Hospitalisation leave', 46, 'fixed', true),
    ('REPLACEMENT LEAVE', 'Public holiday falling on a Saturday, credited manually per occurrence', 0, 'event', true),
    ('CHILDCARE LEAVE', 'Childcare leave', 0, 'tiered', true),
    ('COMPASSIONATE LEAVE', 'Compassionate leave', 0, 'fixed', true),
    ('NATIONAL SERVICE LEAVE', 'NS Leave — no pre-set balance, no cap', 0, 'event', true),
    ('PATERNITY LEAVE', 'Paternity leave (4 weeks)', 20, 'fixed', true),
    ('MATERNITY LEAVE', 'Maternity leave (16 weeks)', 112, 'fixed', true)
on conflict (leave_name) do nothing;

-- Backfill entitlement_mode/is_paid in case rows above already existed
-- from a prior partial run of this migration.
update leave_types set entitlement_mode = 'event', is_paid = true
    where leave_name in ('REPLACEMENT LEAVE', 'NATIONAL SERVICE LEAVE')
    and entitlement_mode is null;
update leave_types set entitlement_mode = 'tiered', is_paid = true
    where leave_name = 'CHILDCARE LEAVE' and entitlement_mode is null;
update leave_types set entitlement_mode = 'fixed', is_paid = true
    where leave_name in ('HOSPITALISATION LEAVE', 'COMPASSIONATE LEAVE',
                          'PATERNITY LEAVE', 'MATERNITY LEAVE')
    and entitlement_mode is null;

-- Every leave type must be classified before the yearly balance
-- generator can rely on entitlement_mode being non-null.
update leave_types set entitlement_mode = 'fixed' where entitlement_mode is null;

alter table leave_types validate constraint leave_types_entitlement_mode_check;


-- ---------------------------------------------------------------------
-- 2. leave_policy_tiers — tier catalogue for tiered leave types
-- ---------------------------------------------------------------------

create table if not exists leave_policy_tiers (
    id uuid primary key default uuid_generate_v4(),
    leave_type_id uuid not null references leave_types(id) on delete cascade,
    tier_name text not null,
    days integer not null,
    created_at timestamp default now(),
    updated_at timestamp default now(),
    unique (leave_type_id, tier_name)
);

create index if not exists idx_leave_policy_tiers_leave_type
    on leave_policy_tiers(leave_type_id);

-- Annual Leave tiers: 21 / 20 / 14 / 11 / 10 days.
-- The 10-day tier is the one that grows +1/year after 3 years' tenure,
-- capped at 14 — handled in application code (see
-- app/leaves/services.py recompute_annual_leave_tenure_tiers), not here.
insert into leave_policy_tiers (leave_type_id, tier_name, days)
select lt.id, tier.tier_name, tier.days
from leave_types lt
cross join (values
    ('21 DAYS', 21),
    ('20 DAYS', 20),
    ('14 DAYS', 14),
    ('11 DAYS', 11),
    ('10 DAYS', 10)
) as tier(tier_name, days)
where lt.leave_name = 'ANNUAL LEAVE'
on conflict (leave_type_id, tier_name) do nothing;

-- Childcare Leave tiers: 6 / 2 days.
insert into leave_policy_tiers (leave_type_id, tier_name, days)
select lt.id, tier.tier_name, tier.days
from leave_types lt
cross join (values
    ('6 DAYS', 6),
    ('2 DAYS', 2)
) as tier(tier_name, days)
where lt.leave_name = 'CHILDCARE LEAVE'
on conflict (leave_type_id, tier_name) do nothing;


-- ---------------------------------------------------------------------
-- 3. employee_leave_tier — HR's per-employee tier assignment
-- ---------------------------------------------------------------------

create table if not exists employee_leave_tier (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid not null references employees(id) on delete cascade,
    leave_type_id uuid not null references leave_types(id) on delete cascade,
    tier_id uuid not null references leave_policy_tiers(id) on delete restrict,
    assigned_by uuid references employees(id) on delete set null,
    created_at timestamp default now(),
    updated_at timestamp default now(),
    unique (employee_id, leave_type_id)
);

create index if not exists idx_employee_leave_tier_employee
    on employee_leave_tier(employee_id);


-- ---------------------------------------------------------------------
-- 4. leave_eligibility_rules — exclusion rules per leave type
-- ---------------------------------------------------------------------
-- One row = "an employee whose <field> equals <value> is / is not
-- eligible for this leave type". `field` is one of nationality,
-- marital_status, gender, employee_type (employee_type is derived at
-- evaluation time from is_field_employee(), not a stored column — see
-- app/core/helpers/employee_helper.py).

create table if not exists leave_eligibility_rules (
    id uuid primary key default uuid_generate_v4(),
    leave_type_id uuid not null references leave_types(id) on delete cascade,
    field text not null,
    value text not null,
    eligible boolean not null,
    created_at timestamp default now(),
    unique (leave_type_id, field, value)
);

alter table leave_eligibility_rules
    add constraint leave_eligibility_rules_field_check
    check (field in ('nationality', 'marital_status', 'gender', 'employee_type'))
    not valid;
alter table leave_eligibility_rules validate constraint leave_eligibility_rules_field_check;

create index if not exists idx_leave_eligibility_rules_leave_type
    on leave_eligibility_rules(leave_type_id);

-- NS Leave: foreigners are not eligible.
insert into leave_eligibility_rules (leave_type_id, field, value, eligible)
select lt.id, 'nationality', 'Foreigner', false
from leave_types lt where lt.leave_name = 'NATIONAL SERVICE LEAVE'
on conflict (leave_type_id, field, value) do nothing;

-- Paternity / Maternity / Childcare: single employees are not eligible.
insert into leave_eligibility_rules (leave_type_id, field, value, eligible)
select lt.id, 'marital_status', 'Single', false
from leave_types lt
where lt.leave_name in ('PATERNITY LEAVE', 'MATERNITY LEAVE', 'CHILDCARE LEAVE')
on conflict (leave_type_id, field, value) do nothing;

-- Paternity: female employees are not eligible.
insert into leave_eligibility_rules (leave_type_id, field, value, eligible)
select lt.id, 'gender', 'Female', false
from leave_types lt where lt.leave_name = 'PATERNITY LEAVE'
on conflict (leave_type_id, field, value) do nothing;

-- Maternity: male employees are not eligible.
insert into leave_eligibility_rules (leave_type_id, field, value, eligible)
select lt.id, 'gender', 'Male', false
from leave_types lt where lt.leave_name = 'MATERNITY LEAVE'
on conflict (leave_type_id, field, value) do nothing;

-- Replacement Leave: field employees are not eligible (office-only).
insert into leave_eligibility_rules (leave_type_id, field, value, eligible)
select lt.id, 'employee_type', 'field', false
from leave_types lt where lt.leave_name = 'REPLACEMENT LEAVE'
on conflict (leave_type_id, field, value) do nothing;


-- ---------------------------------------------------------------------
-- 5. leave_replacement_credits — manual, event-based, Replacement Leave only
-- ---------------------------------------------------------------------

create table if not exists leave_replacement_credits (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid not null references employees(id) on delete cascade,
    public_holiday_date date not null,
    credited_by uuid references employees(id) on delete set null,
    credited_date date not null default current_date,
    expiry_date date not null,
    used boolean not null default false,
    used_leave_request_id uuid references leave_requests(id) on delete set null,
    created_at timestamp default now(),
    updated_at timestamp default now()
);

create index if not exists idx_leave_replacement_credits_employee
    on leave_replacement_credits(employee_id);

create index if not exists idx_leave_replacement_credits_unused
    on leave_replacement_credits(employee_id, used)
    where used = false;


-- ---------------------------------------------------------------------
-- 6. holidays — SG-shifted date support
-- ---------------------------------------------------------------------
-- holidays.holiday_date must already hold the Sunday-shifted date (i.e.
-- what MOM actually observes as the day off), not the raw calendar
-- date the holiday falls on. is_sunday_shifted flags rows where the
-- observed date differs from the holiday's real calendar date, and
-- raw_holiday_date preserves that real date — Replacement Leave credit
-- logic (a PH falling on a *Saturday*) needs the real day-of-week, and
-- shifted-to-Monday holidays would otherwise look like they fell on a
-- Monday.

alter table holidays add column if not exists raw_holiday_date date;
alter table holidays add column if not exists is_sunday_shifted boolean not null default false;

-- app/holidays/schemas.py (CreateHolidayRequest) and services.py
-- (get_holidays' country filter) have referenced holidays.country since
-- they were written, but -- like employees.gender/marital_status/
-- nationality above -- no prior migration actually added the column,
-- so every country filter/insert has been silently broken.
alter table holidays add column if not exists country text not null default 'SG';

create index if not exists idx_holidays_holiday_date on holidays(holiday_date);
create index if not exists idx_holidays_country on holidays(country);