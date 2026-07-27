-- =====================================
-- LEAVE MODULE — NEW PERMISSION SEED
-- =====================================
-- The Leave module previously had no working permission checks at all
-- (see REFACTOR_NOTES.md). `APPROVE_LEAVE` already existed and was
-- already seeded in 002_role_permissions_seed.sql (HR ADMIN, MANAGER,
-- OPERATIONS MANAGER), so it's reused as-is for the approve/reject route.
--
-- This migration adds one new permission, `VIEW_LEAVE_REQUESTS`, used to
-- distinguish "company-wide leave visibility" (HR/Admin — GET /leaves)
-- from "approval scoped to my own reports" (Manager — the existing
-- APPROVE_LEAVE permission, now enforced with an ownership check in
-- app/leaves/services.update_leave_status via the employee manager
-- chain). Safe to re-run: both inserts use ON CONFLICT DO NOTHING.

insert into permissions (permission_name, module)
values ('VIEW_LEAVE_REQUESTS', 'LEAVE')
on conflict (permission_name) do nothing;

-- HR ADMIN: full company-wide leave visibility + approval (APPROVE_LEAVE
-- already granted in 002_role_permissions_seed.sql)
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR ADMIN'
  and p.permission_name = 'VIEW_LEAVE_REQUESTS'
on conflict (role_id, permission_id) do nothing;

-- HR EXECUTIVE: can view all leave requests for reporting purposes, but
-- was not previously granted APPROVE_LEAVE, so this is view-only unless
-- 002 is also updated to grant them APPROVE_LEAVE.
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR EXECUTIVE'
  and p.permission_name = 'VIEW_LEAVE_REQUESTS'
on conflict (role_id, permission_id) do nothing;

-- SUPER ADMIN needs no row — app/core/rbac.py grants it every
-- permission unconditionally.
