-- =====================================
-- ATTENDANCE MODULE — PERMISSION SEED
-- =====================================
-- sql/002_role_permissions_seed.sql already seeded VIEW_ATTENDANCE fairly
-- broadly (EMPLOYEE, VIEWER, MANAGER, HR ADMIN/EXECUTIVE, INSPECTION
-- MANAGER all have it), which is fine as a general "can use attendance
-- features" gate, but it doesn't distinguish "see your own / your
-- reports' attendance" from "see every employee's attendance company-
-- wide" — those need to be different things. This adds two more
-- specific permissions:
--
--   VIEW_ALL_ATTENDANCE          company-wide attendance list, a single
--                                 employee's full record regardless of
--                                 reporting line, and analytics — HR
--                                 ADMIN / HR EXECUTIVE only.
--   APPROVE_ATTENDANCE_CORRECTION  regularization approval, mirroring
--                                 APPROVE_LEAVE's existing distribution
--                                 (HR ADMIN, MANAGER, OPERATIONS
--                                 MANAGER) — combined in
--                                 app/attendance/services.py with a
--                                 manager-chain ownership check, the
--                                 same pattern as Leave approval.
--
-- Safe to re-run: all inserts use ON CONFLICT DO NOTHING.

insert into permissions (permission_name, module)
values
    ('VIEW_ALL_ATTENDANCE', 'ATTENDANCE'),
    ('APPROVE_ATTENDANCE_CORRECTION', 'ATTENDANCE')
on conflict (permission_name) do nothing;

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('HR ADMIN', 'HR EXECUTIVE')
  and p.permission_name = 'VIEW_ALL_ATTENDANCE'
on conflict (role_id, permission_id) do nothing;

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('HR ADMIN', 'MANAGER', 'OPERATIONS MANAGER')
  and p.permission_name = 'APPROVE_ATTENDANCE_CORRECTION'
on conflict (role_id, permission_id) do nothing;
