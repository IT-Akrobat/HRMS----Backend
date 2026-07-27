-- =====================================
-- DOCUMENTS MODULE — PERMISSION SEED
-- =====================================
-- The Documents module previously had zero permission checks — any
-- authenticated user could list every employee's documents
-- (GET /documents), read/update/delete any single document, and fetch
-- any employee's document list via GET /documents/employee/{id}
-- (flagged as a Critical finding in REFACTOR_NOTES.md).
--
-- This adds four permissions, following the same CRUD pattern as
-- Payroll's CREATE_PAYROLL / VIEW_PAYROLL / EDIT_PAYROLL / DELETE_PAYROLL.
-- Safe to re-run: all inserts use ON CONFLICT DO NOTHING.

insert into permissions (permission_name, module)
values
    ('CREATE_DOCUMENT', 'DOCUMENTS'),
    ('VIEW_DOCUMENTS', 'DOCUMENTS'),
    ('EDIT_DOCUMENT', 'DOCUMENTS'),
    ('DELETE_DOCUMENT', 'DOCUMENTS')
on conflict (permission_name) do nothing;

-- HR ADMIN: full document management
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR ADMIN'
  and p.permission_name in ('CREATE_DOCUMENT', 'VIEW_DOCUMENTS', 'EDIT_DOCUMENT', 'DELETE_DOCUMENT')
on conflict (role_id, permission_id) do nothing;

-- HR EXECUTIVE: create/view/edit, no delete (same split as Payroll)
insert into role_permissions (role_id, permission_id)
select r.id, p.id
from roles r, permissions p
where r.role_name = 'HR EXECUTIVE'
  and p.permission_name in ('CREATE_DOCUMENT', 'VIEW_DOCUMENTS', 'EDIT_DOCUMENT')
on conflict (role_id, permission_id) do nothing;

-- Deliberately NOT granted to MANAGER / OPERATIONS MANAGER / INSPECTION
-- MANAGER: employee documents (contracts, PAN/Aadhaar copies, ID proofs)
-- are treated as confidential and restricted to HR/Admin + the owning
-- employee's own self-service view, not opened up to the reporting-
-- manager hierarchy the way Leave/Attendance are. Revisit if the
-- business wants managers to see e.g. certifications but not ID
-- documents — that would need a `document_type`-level permission split,
-- which the current schema doesn't support yet.
--
-- SUPER ADMIN needs no rows — app/core/rbac.py grants it every
-- permission unconditionally.
