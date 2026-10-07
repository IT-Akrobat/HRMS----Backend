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