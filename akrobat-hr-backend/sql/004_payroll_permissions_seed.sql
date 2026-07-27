-- =====================================================================
-- Akrobat HRMS — payroll RBAC hardening
-- Run after sql/001_schema.sql and sql/002_role_permissions_seed.sql
-- =====================================================================
-- Companion to the code change in app/payroll/routes.py +
-- app/payroll/services.py: payroll previously had NO permission check
-- at all (every route only required `get_current_user`), so any
-- authenticated employee could view, edit, or delete any other
-- employee's salary record. This migration adds the permissions the
-- new `require_permission(...)` dependencies on those routes expect.
--
-- Safe to re-run: permissions/role_permissions both have unique
-- constraints and every insert below uses ON CONFLICT DO NOTHING.
-- =====================================================================


-- =====================================
-- NEW PERMISSIONS
-- =====================================

insert into permissions (permission_name, module) values
('CREATE_PAYROLL', 'PAYROLL'),
('VIEW_PAYROLL', 'PAYROLL'),
('EDIT_PAYROLL', 'PAYROLL'),
('DELETE_PAYROLL', 'PAYROLL')
on conflict (permission_name) do nothing;


-- =====================================
-- ROLE ASSIGNMENTS
-- =====================================
-- SUPER ADMIN bypasses permission checks entirely (see
-- app/core/rbac.py), so it's not seeded here on purpose.
--
-- HR ADMIN: full payroll access.
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR ADMIN'
  and p.permission_name in ('CREATE_PAYROLL', 'VIEW_PAYROLL', 'EDIT_PAYROLL', 'DELETE_PAYROLL')
on conflict (role_id, permission_id) do nothing;

-- HR EXECUTIVE: can generate and view payroll, not delete it — deletion
-- is left to HR ADMIN/SUPER ADMIN only, matching the sensitivity of the
-- data.
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR EXECUTIVE'
  and p.permission_name in ('CREATE_PAYROLL', 'VIEW_PAYROLL', 'EDIT_PAYROLL')
on conflict (role_id, permission_id) do nothing;

-- MANAGER, OPERATIONS MANAGER, INSPECTION MANAGER, EMPLOYEE, VIEWER:
-- deliberately NOT granted any payroll permission. Employees still see
-- their own payslips via GET /payroll/my and GET /payroll/{id} (which
-- allows the owning employee through even without VIEW_PAYROLL — see
-- app/payroll/services.get_payroll). Managers do not get visibility
-- into their team's pay in this pass; add a VIEW_TEAM_PAYROLL-style
-- permission later if that's actually wanted, rather than granting the
-- broad VIEW_PAYROLL (which would expose the whole company).
