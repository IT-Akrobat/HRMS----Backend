-- =====================================================================
-- OT Calculator: HR / Super Admin manual OT edits (one row per
-- employee per day). Run AFTER 034_ot_eligible_staff.sql. Safe to re-run.
-- =====================================================================
CREATE TABLE IF NOT EXISTS ot_adjustments (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    attendance_date date NOT NULL,
    manual_ot_hours numeric(4,1) NOT NULL CHECK (manual_ot_hours >= 0 AND manual_ot_hours <= 24),
    note text,
    updated_by uuid,
    created_at timestamp DEFAULT now(),
    updated_at timestamp DEFAULT now(),
    UNIQUE (employee_id, attendance_date)
);

CREATE INDEX IF NOT EXISTS ot_adjustments_date_idx ON ot_adjustments (attendance_date);



-- 034_leave_half_days.sql
--
-- The 2026 Singapore leave sheet (Leave_Record_for_App.xlsx) carries half-day
-- figures (e.g. 8.5 taken, 22.5 balance). leave_balances.* were created as
-- INTEGER in 001_schema.sql, so those values cannot be stored as-is.
--
-- Run BEFORE scripts/import_leave_balances.py.

alter table leave_balances
    alter column total_days     type numeric(5,1) using total_days::numeric,
    alter column used_days      type numeric(5,1) using used_days::numeric,
    alter column remaining_days type numeric(5,1) using remaining_days::numeric;

alter table leave_balances
    alter column total_days     set default 0,
    alter column used_days      set default 0,
    alter column remaining_days set default 0;

-- leave_requests.total_days stays INTEGER on purpose: apply_leave() computes it
-- as whole calendar days, so half-day *applications* are not supported yet.

-- =====================================================================
-- Singapore leave rules (Leave_Record_for_App.xlsx request)
-- Run AFTER 033.sql (which already contains the half-day numeric change
-- for leave_balances). Safe to re-run.
-- =====================================================================

-- 1. Who gets which leave scheme -----------------------------------------
--   SG_LIST   : on the Singapore leave sheet -> Annual, MC, Replacement,
--               Childcare (only if tier assigned). Sees balances.
--   MC_ONLY   : everyone else in Singapore -> MC application only,
--               no balances shown.
--   STANDARD  : previous behaviour (Chennai staff etc.), unchanged.
alter table employees add column if not exists leave_scheme text not null default 'MC_ONLY';
alter table employees drop constraint if exists employees_leave_scheme_check;
alter table employees add constraint employees_leave_scheme_check
    check (leave_scheme in ('SG_LIST', 'MC_ONLY', 'STANDARD'));

-- Chennai / India staff keep their existing leave behaviour.
update employees set leave_scheme = 'STANDARD'
where work_location ilike '%chennai%' or work_location ilike '%india%'
   or id in (select employee_id from employee_leave_overrides);

-- 2. One leave manager per employee ---------------------------------------
alter table employees add column if not exists leave_manager_id uuid references employees(id) on delete set null;
create index if not exists idx_employees_leave_manager on employees(leave_manager_id);

-- 3. HR/Super-Admin-only leave types (Hospitalisation, Maternity) ----------
alter table leave_types add column if not exists hr_managed boolean not null default false;
update leave_types set hr_managed = true
where leave_name in ('HOSPITALISATION LEAVE', 'MATERNITY LEAVE');

-- 4. Half days + balance hold on apply -------------------------------------
alter table leave_requests alter column total_days type numeric(4,1) using total_days::numeric;
alter table leave_requests add column if not exists is_half_day boolean not null default false;
-- true once the days have been taken out of the balance (done at apply time)
alter table leave_requests add column if not exists balance_deducted boolean not null default false;
-- replacement credits held by this request: [{"credit_id": "...", "days": 1}]
alter table leave_requests add column if not exists replacement_allocation jsonb;

alter table leave_replacement_credits add column if not exists days numeric(3,1) not null default 1;
alter table leave_replacement_credits add column if not exists used_days numeric(3,1) not null default 0;
update leave_replacement_credits set used_days = days where used = true and used_days = 0;

-- 5. Medical certificate (MC) flow ------------------------------------------
-- mc_status: AWAITING_CERTIFICATE -> CERTIFICATE_UPLOADED -> VALIDATED
alter table leave_requests add column if not exists mc_status text;
alter table leave_requests add column if not exists mc_certificate_path text;
alter table leave_requests add column if not exists mc_certificate_name text;
alter table leave_requests add column if not exists mc_uploaded_at timestamp;
alter table leave_requests add column if not exists mc_validated_by uuid references employees(id) on delete set null;
alter table leave_requests add column if not exists mc_validated_at timestamp;
alter table leave_requests add column if not exists mc_reminder_sent_at timestamp;
alter table leave_requests drop constraint if exists leave_requests_mc_status_check;
alter table leave_requests add constraint leave_requests_mc_status_check
    check (mc_status is null or mc_status in ('AWAITING_CERTIFICATE', 'CERTIFICATE_UPLOADED', 'VALIDATED'));
create index if not exists idx_leave_requests_mc_pending
    on leave_requests(applied_date) where mc_status is not null and mc_status <> 'VALIDATED';



    -- =====================================================================
-- NOTIFICATIONS -- per-user auto-delete (retention) setting
-- =====================================================================
-- Each employee picks, on the Notifications page, how long their
-- notifications are kept: 7 (one week), 14 (two weeks) or 30 (one month)
-- days. NULL = never chose one, nothing is auto-deleted.
-- Read/applied by app/notifications/services.py (only that employee's
-- rows are ever deleted).
-- =====================================================================

alter table notification_preferences
    add column if not exists notification_retention_days integer;

alter table notification_preferences
    drop constraint if exists notification_preferences_retention_days_check;

alter table notification_preferences
    add constraint notification_preferences_retention_days_check
    check (notification_retention_days is null or notification_retention_days in (7, 14, 30));
    -- Maternity Leave is no longer HR-managed: Super Admin sets the days on the
-- user form and the employee then sees it and applies for it themselves
-- (same as Paternity Leave). Hospitalisation stays HR-managed.
update leave_types set hr_managed = false
where leave_name = 'MATERNITY LEAVE';



-- =====================================================================
-- MC: days are calculated from the END DATE ON THE CERTIFICATE.
-- The employee applies for MC (e.g. 24-25 Oct) and uploads the certificate
-- later (e.g. 26 Oct). The certificate's end date is stored here; the
-- leave's end_date / total_days only become final when HR validates.
-- Safe to re-run.
-- =====================================================================
alter table leave_requests add column if not exists mc_end_date date;



-- =====================================================================
-- Resigned employees (Super Admin only archive)
-- Run AFTER 034. Safe to re-run.
-- =====================================================================
-- Lifecycle of one row:
--   Serving Notice  -> employee still works, still appears everywhere
--   Relieved        -> last working day reached (or "Relieve now"):
--                      employees.employment_status = 'Resigned',
--                      login disabled, removed from active lists
--   Withdrawn       -> resignation cancelled during notice period
-- Nothing is ever deleted: ON DELETE RESTRICT stops the employee row
-- (and therefore all attendance / leave / payroll history) being removed.

create table if not exists employee_resignations (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null references employees(id) on delete restrict,

    resignation_date date not null,
    last_working_day date not null,
    notice_period_days integer,

    reason_category text not null,
    reason_remarks text,
    admin_remarks text,                 -- private, Super Admin only
    eligible_for_rehire boolean,

    status text not null default 'Serving Notice'
        check (status in ('Serving Notice', 'Relieved', 'Withdrawn')),

    accepted_by uuid references employees(id) on delete set null,
    accepted_at timestamptz default now(),
    relieved_at timestamptz,

    exit_checklist jsonb not null default '{
        "asset_returned": false,
        "site_handover": false,
        "knowledge_transfer": false,
        "exit_interview": false,
        "access_disabled": false
    }'::jsonb,

    pending_salary numeric(12,2) not null default 0,
    leave_encashment numeric(12,2) not null default 0,
    deductions numeric(12,2) not null default 0,
    net_payable numeric(12,2) generated always as
        (coalesce(pending_salary,0) + coalesce(leave_encashment,0) - coalesce(deductions,0)) stored,
    settlement_status text not null default 'Pending'
        check (settlement_status in ('Pending', 'Paid')),
    settlement_paid_on date,

    -- department / designation / manager as they were when the person resigned,
    -- so the archive stays correct even if those records change later
    snapshot jsonb not null default '{}'::jsonb,

    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

-- one ACTIVE resignation per employee (a withdrawn one doesn't block a new one)
create unique index if not exists employee_resignations_one_active
    on employee_resignations (employee_id) where status <> 'Withdrawn';
create index if not exists employee_resignations_status_idx
    on employee_resignations (status);
create index if not exists employee_resignations_lwd_idx
    on employee_resignations (last_working_day);

-- Only the backend (service role) touches this table. RLS on + no policies
-- means the public anon key can never read it.
alter table employee_resignations enable row level security;


-- 037: Chennai full-day Saturday shift (9:00 AM - 6:00 PM)
--
-- Chennai staff who work Saturdays do 9:00-18:00 instead of the half-day
-- Office / Inspection Saturday timings. _get_employee_shift() looks this
-- row up by exact name when employees.work_location mentions "Chennai".
-- Idempotent: safe to run more than once.

insert into shifts (shift_name, start_time, end_time, working_hours, break_duration, grace_period, status)
select 'OFFICE - SATURDAY (CHENNAI 9:00-6:00)', '09:00', '18:00', 9, 0, 10, 'Active'
where not exists (
    select 1 from shifts where shift_name = 'OFFICE - SATURDAY (CHENNAI 9:00-6:00)'
);


-- =====================================================================
-- Saturday Swap
--
-- An employee on the "2nd & 4th Saturday" pattern (employees.alternate_saturday)
-- can swap ONE of their regular working Saturdays (off_date) for ONE of their
-- regular off Saturdays (work_date). Once the reporting manager approves it:
--   * work_date  -> treated as a working day (check-in allowed, attendance
--                   recorded as Present, shift/late rules apply)
--   * off_date   -> treated as a week-off (no Absent / LOP)
-- Nothing else is stored: app/attendance/services.py::_get_employee_shift()
-- reads this table, so attendance, working-day status and leave day-counting
-- all stay consistent automatically.
--
-- Safe to re-run.
-- =====================================================================
CREATE TABLE IF NOT EXISTS saturday_swaps (
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    work_date date NOT NULL,   -- normally-off Saturday the employee WILL work
    off_date date NOT NULL,    -- normally-working Saturday the employee will skip
    reason text NOT NULL,
    status text NOT NULL DEFAULT 'Pending'
        CHECK (status IN ('Pending', 'Approved', 'Rejected', 'Cancelled')),
    approved_by uuid,
    approved_date timestamptz,
    comments text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now(),
    CHECK (extract(dow FROM work_date) = 6),
    CHECK (extract(dow FROM off_date) = 6),
    CHECK (work_date <> off_date)
);

-- A given Saturday can be part of only one live (Pending / Approved) swap
-- per employee.
CREATE UNIQUE INDEX IF NOT EXISTS saturday_swaps_work_live_uq
    ON saturday_swaps (employee_id, work_date)
    WHERE status IN ('Pending', 'Approved');

CREATE UNIQUE INDEX IF NOT EXISTS saturday_swaps_off_live_uq
    ON saturday_swaps (employee_id, off_date)
    WHERE status IN ('Pending', 'Approved');

CREATE INDEX IF NOT EXISTS saturday_swaps_employee_idx
    ON saturday_swaps (employee_id, status);



    -- =====================================================================
-- 035_region_audit_logs.sql
-- Audit logs (and login lockouts) follow the region of the employee who
-- performed the action (audit_logs.employee_id = the actor).
--
--   Chennai staff action   -> CHENNAI
--   Singapore staff action -> SINGAPORE
--   system / no employee   -> NULL  (visible in both regions)
--
-- Needs 034 (set_region_from_employee function + employees.region).
-- Safe to re-run.
-- =====================================================================

do $$
declare
    t text;
begin
    foreach t in array array['audit_logs', 'login_lockouts'] loop
        if to_regclass('public.' || t) is null then
            raise notice 'skip % (table not found)', t;
            continue;
        end if;

        execute format('alter table %I add column if not exists region text', t);
        execute format('create index if not exists %I on %I (region)',
                       t || '_region_idx', t);

        -- backfill old rows from the actor
        execute format(
            'update %I x set region = e.region
               from employees e
              where x.employee_id = e.id and x.region is null', t);

        -- new rows
        execute format('drop trigger if exists trg_%s_region on %I', t, t);
        execute format(
            'create trigger trg_%s_region
               before insert on %I
               for each row execute function set_region_from_employee()', t, t);
    end loop;
end $$;

-- check
select region, count(*) from audit_logs group by region;


-- =====================================================================
-- 034_region_scoping.sql
-- Chennai / Singapore complete data separation.
--
-- region values: 'CHENNAI' | 'SINGAPORE'
--
-- STRICT tables   (employee data)  -> every row MUST belong to one region.
--                                     region is copied from employees.region
--                                     automatically by a trigger.
-- SHARED-OK tables (master data)   -> region NULL = shared by both regions,
--                                     otherwise visible only in that region.
--
-- Safe to re-run (idempotent).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. employees.region  (the source of truth)
-- ---------------------------------------------------------------------
alter table employees add column if not exists region text;

alter table employees drop constraint if exists employees_region_chk;
alter table employees
    add constraint employees_region_chk
    check (region is null or region in ('CHENNAI', 'SINGAPORE'));

-- Backfill from the old free-text work_location.
-- RULE: work location mentions Chennai (or India) -> CHENNAI,
--       everyone else (Singapore, blank, anything else) -> SINGAPORE.
update employees
set region = case
        when work_location ilike '%chennai%' or work_location ilike '%india%'
            then 'CHENNAI'
        else 'SINGAPORE'
    end
where region is null;

create index if not exists employees_region_idx on employees (region);

-- Keep region in step with work_location when region isn't supplied.
create or replace function employees_derive_region() returns trigger as $$
begin
    if new.region is null then
        if new.work_location ilike '%chennai%' or new.work_location ilike '%india%' then
            new.region := 'CHENNAI';
        else
            new.region := 'SINGAPORE';
        end if;
    end if;
    return new;
end;
$$ language plpgsql;

drop trigger if exists trg_employees_derive_region on employees;
create trigger trg_employees_derive_region
    before insert or update of work_location, region on employees
    for each row execute function employees_derive_region();

-- ---------------------------------------------------------------------
-- 2. STRICT tables: copy region from the employee row
-- ---------------------------------------------------------------------
create or replace function set_region_from_employee() returns trigger as $$
begin
    if new.region is null and new.employee_id is not null then
        select e.region into new.region
        from employees e
        where e.id = new.employee_id;
    end if;
    return new;
end;
$$ language plpgsql;

do $$
declare
    t text;
    strict_tables text[] := array[
        'attendance',
        'attendance_corrections',
        'attendance_site_visits',
        'attendance_outdoor_visits',
        'employee_site_assignments',
        'employee_shift_history',
        'leave_requests',
        'leave_balances',
        'leave_replacement_credits',
        'employee_leave_overrides',
        'employee_leave_tier',
        'overtime_requests',
        'overtime_summary',
        'ot_adjustments',
        'payroll',
        'employee_resignations',
        'saturday_swaps',
        'employee_documents',
        'documents',
        'expenses'
    ];
begin
    foreach t in array strict_tables loop
        if to_regclass('public.' || t) is null then
            raise notice 'skip % (table not found)', t;
            continue;
        end if;

        begin
            execute format('alter table %I add column if not exists region text', t);
            execute format('create index if not exists %I on %I (region)',
                           t || '_region_idx', t);
            execute format(
                'update %I x set region = e.region
                   from employees e
                  where x.employee_id = e.id and x.region is null', t);
            execute format('drop trigger if exists trg_%s_region on %I', t, t);
            execute format(
                'create trigger trg_%s_region
                   before insert on %I
                   for each row execute function set_region_from_employee()', t, t);
        exception when others then
            raise notice 'region setup failed for %: %', t, sqlerrm;
        end;
    end loop;
end $$;

-- ---------------------------------------------------------------------
-- 3. SHARED-OK master tables (NULL = shared)
-- ---------------------------------------------------------------------
do $$
declare
    t text;
    master_tables text[] := array[
        'departments',
        'designations',
        'shifts',
        'announcements',
        'locations',
        'company_locations'
    ];
begin
    foreach t in array master_tables loop
        if to_regclass('public.' || t) is null then
            raise notice 'skip % (table not found)', t;
            continue;
        end if;
        execute format('alter table %I add column if not exists region text', t);
        execute format('create index if not exists %I on %I (region)',
                       t || '_region_idx', t);
    end loop;
end $$;

-- Sites / office locations: guess from the address text.
update locations
set region = case
        when coalesce(address, '') || ' ' || location_name ilike '%chennai%'
          or coalesce(address, '') || ' ' || location_name ilike '%india%'
          or coalesce(address, '') || ' ' || location_name ilike '%tamil%'
            then 'CHENNAI'
        else 'SINGAPORE'
    end
where region is null;

-- Announcements: take the region of whoever posted it.
update announcements a
set region = e.region
from employees e
where a.created_by = e.id and a.region is null;

-- Departments / designations / shifts stay NULL (= shared) until you
-- assign them. Examples:
--   update departments set region = 'SINGAPORE' where department_name in ('...');

-- ---------------------------------------------------------------------
-- 4. CHECK: employees that still have no region (fix these manually!)
-- ---------------------------------------------------------------------
-- select id, employee_id, full_name, work_location
-- from employees where region is null order by full_name;
--
-- update employees set region = 'CHENNAI'   where id = '...';
-- update employees set region = 'SINGAPORE' where id = '...';


-- Part-time employees: no fixed shift, no leave, no OT, no late/early
-- rules. Only worked time (check-in -> check-out, minus recorded breaks)
-- is calculated. Default false => every existing employee is unaffected.
alter table employees
    add column if not exists is_part_time boolean not null default false;