-- =====================================
-- ROLE <-> PERMISSION SEED DATA
-- =====================================
-- role_permissions existed in the schema but was never populated, so
-- app/core/rbac.require_permission would deny everyone except SUPER ADMIN
-- (which bypasses the check) until this is run.
--
-- Adjust freely — this is a sane default, not a hard requirement.
--
-- NOTE: the APPROVE_LEAVE grants below (HR ADMIN, MANAGER, OPERATIONS
-- MANAGER) are revoked by 012_restrict_leave_approval_to_super_admin.sql —
-- company policy is now that only SUPER ADMIN approves/rejects leave. Left
-- in place here as history; run 012 after this file.

-- HR ADMIN: full employee/attendance/leave/reports access
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR ADMIN'
  and p.permission_name in (
    'CREATE_EMPLOYEE','VIEW_EMPLOYEE','EDIT_EMPLOYEE','DELETE_EMPLOYEE',
    'VIEW_ATTENDANCE','EDIT_ATTENDANCE',
    'APPROVE_LEAVE','APPROVE_OVERTIME',
    'VIEW_REPORTS','MANAGE_SETTINGS'
  );

-- HR EXECUTIVE: employee + attendance operations, no settings/delete
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR EXECUTIVE'
  and p.permission_name in (
    'CREATE_EMPLOYEE','VIEW_EMPLOYEE','EDIT_EMPLOYEE',
    'VIEW_ATTENDANCE','EDIT_ATTENDANCE',
    'VIEW_REPORTS'
  );

-- MANAGER / OPERATIONS MANAGER: approvals + team visibility
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name in ('MANAGER','OPERATIONS MANAGER')
  and p.permission_name in (
    'VIEW_EMPLOYEE','VIEW_ATTENDANCE',
    'APPROVE_LEAVE','APPROVE_OVERTIME',
    'VIEW_REPORTS'
  );

-- INSPECTION MANAGER: read-only + approvals within their scope
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'INSPECTION MANAGER'
  and p.permission_name in ('VIEW_EMPLOYEE','VIEW_ATTENDANCE','VIEW_REPORTS');

-- EMPLOYEE: self-service only (own-record scoping is enforced in the
-- service layer, not by this table — see REFACTOR_NOTES.md)
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'EMPLOYEE'
  and p.permission_name in ('VIEW_ATTENDANCE');

-- VIEWER: read-only
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'VIEWER'
  and p.permission_name in ('VIEW_EMPLOYEE','VIEW_ATTENDANCE','VIEW_REPORTS');

-- SUPER ADMIN needs no rows — app/core/rbac.py grants it every permission
-- unconditionally so it can never be locked out by a missing seed row.
