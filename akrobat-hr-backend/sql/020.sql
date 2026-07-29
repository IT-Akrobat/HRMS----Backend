-- =====================================================================
-- NOTIFICATION PREFERENCES -- backing table for the Notifications tab
-- in Settings.jsx (Email notifications / Leave request updates /
-- Announcements / Birthdays & work anniversaries / Attendance reminders)
-- =====================================================================
-- Previously these five toggles only ever persisted to localStorage
-- (Settings.jsx saveNotifications()) -- there was no server-side
-- endpoint for them at all, so they didn't follow the employee across
-- devices and nothing else in the backend could read them.
--
-- One row per employee. "attendance_reminders" defaults to false to
-- match the toggle's default-off state already shown in the UI; the
-- other four default to true, matching Settings.jsx's NOTIF_DEFAULTS.
--
-- app/attendance/services.py::get_attendance_reminder_status() reads
-- attendance_reminders directly from this table (not through the
-- notification_preferences module, to avoid a cross-module import) --
-- if you rename/add columns here, that function needs to stay in sync.
-- =====================================================================

create table if not exists notification_preferences (
    employee_id uuid primary key references employees(id) on delete cascade,
    email_notifications boolean not null default true,
    leave_updates boolean not null default true,
    announcements boolean not null default true,
    celebrations boolean not null default true,
    attendance_reminders boolean not null default false,
    updated_at timestamptz not null default now()
);