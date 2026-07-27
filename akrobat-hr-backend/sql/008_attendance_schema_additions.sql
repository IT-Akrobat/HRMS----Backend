-- =====================================
-- ATTENDANCE MODULE — SCHEMA ADDITIONS
-- =====================================
-- Two groups of nullable, additive columns on `attendance`:
--
-- 1. check_in_latitude / check_in_longitude / check_out_latitude /
--    check_out_longitude — the ORIGINAL (broken) app/attendance/services.py
--    already referenced check_in_lat / check_in_long / check_out_lat /
--    check_out_long on every insert/update, but no such columns (under
--    any name) exist in sql/001_schema.sql. Every check-in/check-out
--    call would have failed against a real database. Named with the
--    fuller `latitude`/`longitude` spelling here for clarity/consistency
--    with `locations.latitude` / `locations.longitude`.
--
-- 2. ip_address / device_info — "Device Tracking" / "Browser Tracking"
--    from the spec, captured at check-in from the request itself (same
--    approach app/core/audit.py already uses for audit log rows).
--
-- Both groups are non-breaking: nullable, no existing row touched, no
-- existing query affected. Safe to re-run (IF NOT EXISTS).

alter table attendance add column if not exists check_in_latitude double precision;
alter table attendance add column if not exists check_in_longitude double precision;
alter table attendance add column if not exists check_out_latitude double precision;
alter table attendance add column if not exists check_out_longitude double precision;

alter table attendance add column if not exists ip_address text;
alter table attendance add column if not exists device_info text;
