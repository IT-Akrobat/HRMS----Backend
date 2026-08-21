-- =====================================================================
-- GRANT VIEW_LEAVE_REQUESTS TO ALL MANAGER-TIER ROLES
-- =====================================================================
-- GET /leaves/team (app/leaves/routes.py) — which backs the frontend's
-- Team Leave Requests and Team Leave History pages — is gated on the
-- VIEW_LEAVE_REQUESTS permission.
--
-- A live check against this project's database
-- (select r.role_name, p.permission_name from role_permissions rp
--  join roles r on r.id = rp.role_id
--  join permissions p on p.id = rp.permission_id
--  where p.permission_name = 'VIEW_LEAVE_REQUESTS') returned only ONE
-- row: HR. None of the earlier seed migrations that were meant to grant
-- this to MANAGER / OPERATIONS MANAGER (005_leave_permissions_seed.sql,
-- 012_restrict_leave_approval_to_super_admin.sql) or to
-- INSPECTION MANAGER / TEAM LEADER (028_...sql) have actually been run
-- against this database — this migration re-grants all of them in one
-- place so there's a single file to run.
--
-- Safe to re-run: ON CONFLICT DO NOTHING.

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in (
    'MANAGER',
    'OPERATIONS MANAGER',
    'INSPECTION MANAGER',
    'TEAM LEADER'
  )
  and p.permission_name = 'VIEW_LEAVE_REQUESTS'
on conflict (role_id, permission_id) do nothing;

-- Verify afterwards:
-- select r.role_name, p.permission_name
-- from role_permissions rp
-- join roles r on r.id = rp.role_id
-- join permissions p on p.id = rp.permission_id
-- where p.permission_name = 'VIEW_LEAVE_REQUESTS'
-- order by r.role_name;


-- Tamil Nadu Government Public Holidays for the year 2026
-- Source: Government of Tamil Nadu notification under Explanation to
-- Section 25 of the Negotiable Instruments Act, 1881
--
-- NOTE: column names (holidays.country / holiday_name / holiday_date)
-- are assumed to match what GET /holidays/?country=IN already returns
-- in this app. Verify against the actual table (e.g.
-- sql/012_holiday_country_and_employee_dob.sql) before running, and
-- adjust the table/column names if they differ.

INSERT INTO holidays (country, holiday_name, holiday_date) VALUES
('IN', 'New Year''s Day', '2026-01-01'),
('IN', 'Pongal', '2026-01-15'),
('IN', 'Thiruvalluvar Day', '2026-01-16'),
('IN', 'Uzhavar Thirunal', '2026-01-17'),
('IN', 'Republic Day', '2026-01-26'),
('IN', 'Thai Poosam', '2026-02-01'),
('IN', 'Telugu New Year''s Day', '2026-03-19'),
('IN', 'Ramzan (Idu''l Fitr)', '2026-03-21'),
('IN', 'Mahaveer Jayanthi', '2026-03-31'),
('IN', 'Annual closing of Accounts for Commercial Banks & Co-operative Banks', '2026-04-01'),
('IN', 'Good Friday', '2026-04-03'),
('IN', 'Tamil New Year''s Day / Dr. B.R. Ambedkar''s Birthday', '2026-04-14'),
('IN', 'May Day', '2026-05-01'),
('IN', 'Bakrid (Idul Azha)', '2026-05-28'),
('IN', 'Muharram (Yaom-E-Shahadath)', '2026-06-26'),
('IN', 'Independence Day', '2026-08-15'),
('IN', 'Milad-un-Nabi (Prophet''s Birthday)', '2026-08-26'),
('IN', 'Krishna Jayanthi', '2026-09-04'),
('IN', 'Vinayakar Chathurthi', '2026-09-14'),
('IN', 'Gandhi Jayanthi', '2026-10-02'),
('IN', 'Ayutha Pooja', '2026-10-19'),
('IN', 'Vijaya Dasami', '2026-10-20'),
('IN', 'Deepavali', '2026-11-08'),
('IN', 'Christmas', '2026-12-25');

-- NOTE: "Annual closing of Accounts..." (S.No. 10, 01.04.2026) is a
-- bank-only holiday per the notification's footnote ("*Applicable only
-- to Commercial Banks and Co-operative Banks in Tamil Nadu"). Remove
-- that row if your company calendar shouldn't include it as a general
-- employee holiday.