-- =====================================================================
-- Remove leftover placeholder designations that leaked into the real
-- departments after the 016.sql merge
-- Run after 001-023.
-- =====================================================================
--
-- WHAT HAPPENED
-- -------------
-- sql/001_schema.sql originally seeded 17 designations with NO
-- department_id at all, including 4 that are not in "Attendance
-- Info.docx":
--   - DRIVER CUM WELDER
--   - ACCOUNTS EXECUTIVE                 (doc only has "Account Executive")
--   - SALES AND MARKETING EXECUTIVE
--   - ADMINISTRATION CUM SALES ASSISTANT (doc only has "Admin Cum Sales Assistant")
--
-- sql/011_team_leader_and_org_structure.sql backfilled those orphan rows
-- onto the OLD placeholder departments (OPERATIONS / FINANCE / SALES AND
-- MARKETING). sql/016.sql then merged those placeholder departments into
-- the real doc departments (OPERATION / ACCOUNT / SALES) and carried
-- these 4 rows along with them — 016.sql's step 4 only deleted 2 of the
-- stray designations (CIVIL ENGINEER, WORK-AT-HEIGHT INSPECTOR), missing
-- these 4.
--
-- Net effect: the Operation designation dropdown showed 6 options
-- instead of the doc's 5 (the extra was "Driver Cum Welder"), and
-- Account / Sales were quietly over too.
--
-- This migration finishes what 016.sql's step 4 started. Any employee
-- currently holding one of these has designation_id cleared automatically
-- (on delete set null) — no employee rows are removed.
-- =====================================================================

delete from designations where designation_name = 'DRIVER CUM WELDER';
delete from designations where designation_name = 'ACCOUNTS EXECUTIVE';
delete from designations where designation_name = 'SALES AND MARKETING EXECUTIVE';
delete from designations where designation_name = 'ADMINISTRATION CUM SALES ASSISTANT';

-- =====================================================================
-- AFTER RUNNING THIS
-- =====================================================================
-- OPERATION  -> Project Manager, Construction Worker,
--               Construction Worker-Cum-Driver, Driver,
--               Construction Worker (Storeman)                [5, matches doc]
-- ACCOUNT    -> Account Executive                              [1, matches doc]
-- SALES      -> Admin Cum Sales Assistant                      [1, matches doc]
-- =====================================================================