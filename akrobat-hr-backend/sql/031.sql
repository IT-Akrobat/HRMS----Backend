-- =====================================================================
-- NOTIFICATION PREFERENCES -- add "Checkout reminders" and "Holiday
-- reminders" toggles
-- =====================================================================
-- Extends notification_preferences (see sql/020.sql) with two more
-- per-employee toggles for the Notifications tab in Settings.jsx:
--
--   checkout_reminders -- the check-out counterpart to
--     attendance_reminders (which only covers a missed check-in).
--     Read directly from this table by
--     app/attendance/services.py::get_checkout_reminder_status(),
--     same pattern attendance_reminders already uses. Defaults to
--     false, matching attendance_reminders' default-off state.
--
--   holiday_reminders -- gates the "Due to <holiday>, tomorrow/today
--     is a holiday" notification sent by
--     app/holidays/services.py::get_holiday_reminder_status(). Unlike
--     the two reminders above this defaults to true: it's informational
--     (so people aren't caught off guard by an office closure) rather
--     than a nag, matching the default-on behavior of announcements/
--     celebrations/leave_updates/email_notifications.
-- =====================================================================

alter table notification_preferences
    add column if not exists checkout_reminders boolean not null default false;

alter table notification_preferences
    add column if not exists holiday_reminders boolean not null default true;