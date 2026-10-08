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