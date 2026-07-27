-- =====================================
-- AUDIT LOGS MODULE — PERMISSION SEED
-- =====================================
-- The Audit Logs module previously had zero permission checks — any
-- authenticated user could read every audit log in the system (who
-- changed what, on any employee's record) and, worse, delete any audit
-- log entry outright. Flagged as a Critical finding in
-- REFACTOR_NOTES.md ("GET /audit-logs readable by any authenticated
-- user, should likely be HR/Admin-only").
--
-- Two permissions:
--   VIEW_AUDIT_LOGS    read access to the audit trail — HR ADMIN.
--   MANAGE_AUDIT_LOGS  manual log creation + deletion — deliberately NOT
--                       granted to any role here, including HR ADMIN.
--                       SUPER ADMIN bypasses require_permission()
--                       entirely (see app/core/rbac.py), so this
--                       effectively makes both routes Super-Admin-only.
--                       Deleting or hand-writing audit trail entries is
--                       higher-risk than reading them (it's how you'd
--                       cover your tracks), so it isn't extended to HR
--                       ADMIN the way other HR permissions are. If you
--                       want HR ADMIN to also manage audit logs, grant
--                       it explicitly — left out on purpose, not by
--                       oversight.
--
-- Safe to re-run: all inserts use ON CONFLICT DO NOTHING.

insert into permissions (permission_name, module)
values
    ('VIEW_AUDIT_LOGS', 'AUDIT_LOGS'),
    ('MANAGE_AUDIT_LOGS', 'AUDIT_LOGS')
on conflict (permission_name) do nothing;

insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR ADMIN'
  and p.permission_name = 'VIEW_AUDIT_LOGS'
on conflict (role_id, permission_id) do nothing;
