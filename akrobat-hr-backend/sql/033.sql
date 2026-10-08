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