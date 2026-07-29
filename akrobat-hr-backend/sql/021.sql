-- =====================================================================
-- EMPLOYEE DATE OF BIRTH
-- =====================================================================
-- app/employees/services.py (update_employee, update_my_profile) and
-- app/employees/schemas.py already read/write "date_of_birth" on the
-- employees table, but no prior migration in this sql/ folder actually
-- creates the column -- so saving it from "My Profile" would fail
-- (PGRST204, column not found) until this runs.
--
-- Also used by app/notifications/services.py::get_celebrations_status()
-- to detect birthdays for the "Birthdays & work anniversaries"
-- notification preference.
-- =====================================================================

alter table employees
    add column if not exists date_of_birth date;