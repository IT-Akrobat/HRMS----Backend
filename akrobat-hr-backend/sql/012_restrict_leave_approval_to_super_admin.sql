-- =====================================
-- LEAVE APPROVAL — RESTRICT TO SUPER ADMIN ONLY
-- =====================================
-- Company policy: only SUPER ADMIN may approve/reject leave requests.
-- app/leaves/routes.py now gates PUT /leaves/{id} with require_role(["SUPER
-- ADMIN"]) directly (not the data-driven APPROVE_LEAVE permission), so this
-- migration just cleans up role_permissions to match reality and keeps
-- read-only leave visibility for HR ADMIN / HR EXECUTIVE / MANAGER /
-- OPERATIONS MANAGER (they can still see requests via GET /leaves and
-- GET /leaves/team, they just can't act on them anymore).
--
-- Safe to re-run.

-- Revoke APPROVE_LEAVE from every role. SUPER ADMIN never had a row here
-- (app/core/rbac.py grants it every permission unconditionally), so this
-- only affects HR ADMIN, MANAGER, OPERATIONS MANAGER, which is the point.
delete from role_permissions
where permission_id in (
  select id from permissions where permission_name = 'APPROVE_LEAVE'
);

-- MANAGER / OPERATIONS MANAGER keep read-only visibility into their team's
-- leave requests (GET /leaves/team now requires VIEW_LEAVE_REQUESTS, not
-- APPROVE_LEAVE — see app/leaves/routes.py).
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('MANAGER', 'OPERATIONS MANAGER')
  and p.permission_name = 'VIEW_LEAVE_REQUESTS'
on conflict (role_id, permission_id) do nothing;
