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