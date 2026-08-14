-- =====================================================================
-- GRANT VIEW_LEAVE_REQUESTS TO INSPECTION MANAGER + TEAM LEADER
-- =====================================================================
-- Bug: GET /leaves/team (app/leaves/routes.py) is gated on
-- VIEW_LEAVE_REQUESTS. 012_restrict_leave_approval_to_super_admin.sql
-- granted that permission to MANAGER and OPERATIONS MANAGER, but two
-- other roles were missed:
--
--   - INSPECTION MANAGER: only ever got VIEW_EMPLOYEE, VIEW_ATTENDANCE,
--     VIEW_REPORTS (002_role_permissions_seed.sql).
--   - TEAM LEADER: only ever got VIEW_EMPLOYEE, VIEW_ATTENDANCE,
--     APPROVE_ATTENDANCE_CORRECTION (011_team_leader_and_org_structure.sql).
--
-- Both roles are normalized to the frontend's "manager" bucket
-- (frontend src/config/roles.js BACKEND_ROLE_MAP) and land on the same
-- Team Leave Requests / Team Leave History pages as MANAGER /
-- OPERATIONS MANAGER — so without this grant, any user with either role
-- gets a 403 "You don't have permission to perform this action
-- (VIEW_LEAVE_REQUESTS)" the moment they open those screens.
--
-- Safe to re-run: ON CONFLICT DO NOTHING.

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('INSPECTION MANAGER', 'TEAM LEADER')
  and p.permission_name = 'VIEW_LEAVE_REQUESTS'
on conflict (role_id, permission_id) do nothing;