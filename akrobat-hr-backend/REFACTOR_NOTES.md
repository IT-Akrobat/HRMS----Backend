# Refactor notes

Being upfront: the brief in `Refactor Prompt.md` (organization/branches/teams,
timesheets, assets, salary structures, full RBAC UI, 2FA, push notifications,
export-ready reports, etc.) describes a multi-month enterprise product, not
something that can be honestly rebuilt in one pass. Rather than generate
hundreds of shallow, untested files to look "complete," this pass makes the
existing backend's *foundations* production-grade and sets a clear pattern
the rest of the modules can follow. Below is exactly what changed, why, and
what's left.

## What actually changed

### 1. `app/core/repository.py` (new)
Every module was calling `supabase_admin.table(...)` directly inside
services, which duplicates the same select/filter/insert/update boilerplate
~25 times and makes services hard to test. Added a generic
`SupabaseRepository` base class (list/get/create/update/delete/soft_delete)
that services should depend on instead. `app/employees/services.py` now
uses it as the reference implementation.

### 2. `app/core/audit.py` (new, replaces two duplicate helpers)
There were two different audit-log writers with different signatures
(`app/core/helpers/audit_helper.create_audit_log` and
`app/audit_logs/services.create_audit_log`). Consolidated into one
`record_audit_log()` that:
- never raises (a logging failure must not break the request),
- auto-computes an old/new **field-level diff** instead of just a
  free-text description,
- captures IP address + user agent when you pass it the `Request`,
- falls back to a minimal insert if your `audit_logs` table hasn't been
  migrated to the richer columns yet.

`app/core/helpers/audit_helper.py` is kept as a 3-line shim so existing
imports don't break.

**Action needed:** the diff/details are currently packed into the
`description` column as JSON text because `audit_logs` doesn't have
`old_values`/`new_values` columns. If you want first-class columns, run:
```sql
alter table audit_logs add column old_values jsonb;
alter table audit_logs add column new_values jsonb;
```
and update `record_audit_log()` in `app/core/audit.py` to write them
directly instead of stuffing them into `description`.

### 3. `app/core/rbac.py` (new) + `sql/002_role_permissions_seed.sql` (new)
The schema already had `roles` / `permissions` / `role_permissions` tables,
but nothing used them — every route was locked with `require_role([...])`,
a hardcoded list of role names in code. That's exactly what the brief says
not to do ("Do NOT hardcode permissions").

Added `require_permission("VIEW_EMPLOYEE")` as a FastAPI dependency that
looks up the caller's role → permissions from the database. `SUPER ADMIN`
always passes. `require_role` still exists (it's fine for a handful of
super-admin-only endpoints) but new/updated routes should prefer
`require_permission`.

**Action needed:** `role_permissions` was never seeded, so without
`sql/002_role_permissions_seed.sql` every non-admin request would now be
denied. Run that seed (or adjust it) before deploying this.

### 4. `app/employees/*` — reference refactor
Rewrote `services.py` and `routes.py` to demonstrate the new patterns:
repository layer, permission-based RBAC, and audit logging with old/new
value diffs on every create/update/delete. Also fixed a real bug in the
original `update_employee`/`delete_employee`: they called
`get_employee_or_404(...).data`, but that helper already returns the
unwrapped dict — `.data` on a dict would have raised `AttributeError` on
every update/delete once it reached that line (it worked before because
the `try/except Exception` swallowed it into a generic 500, which is also
worth knowing).

### 5. `sql/001_schema.sql` (new)
Consolidated the schema you'd shared into one runnable file, in FK-safe
order, with one fix: the original had `audit_logs` created twice with
different columns (once in the core file, once in the attendance file) —
running both as-is would error. Kept the richer version once.

## What's deliberately *not* done in this pass

These are real gaps against the full brief. Doing them well means new
tables + migrations + services + routes each, which is why they're listed
as follow-ups rather than stubbed out:

- **Organization hierarchy** (Branches, Teams) — schema currently stops at
  Department → Designation → Employee. Adding Branch/Team is a schema
  change (new tables + `employees.branch_id`/`team_id`) plus new module.
- **Repository/RBAC/audit pattern applied to every other module** —
  attendance, leaves, overtime, payroll, projects, expenses, etc. still
  call `supabase_admin` directly and use `require_role`. The pattern is
  proven in `employees/`; rolling it out module-by-module is mechanical
  but touches ~25 files.
- **Assets, Timesheets, Salary Structure/Components, PF/ESI** — no tables
  exist yet; brief says "keep architecture ready," not implement now.
- **Employee sub-tables split** (bank details, skills, certifications,
  increment history) — partially exists (education, experience, emergency
  contacts); bank/skills/certifications/assets are missing.
- **User Settings** (theme, language, 2FA, sessions/devices) — no module.
- **"My Team" scoping** (manager sees only their reports, with a
  professional-fields-only profile view) — needs a `get_direct_reports()`
  helper plus a trimmed response schema; not yet built.
- **JWT refresh tokens, rate limiting** — auth currently defers entirely
  to Supabase Auth (reasonable), but there's no app-level rate limiting.

## Update: `sql/003_attendance_info_seed.sql` (new)
The company sent over real working-hours and department/occupation data
("Attendance Info.docx"). Added a third migration that seeds it:
- **Departments**: QS, Inspection, Design, HR, Account, Operation,
  Purchasing & Logistics, Sales — the actual names from the doc. These
  are added alongside (not replacing) the placeholder departments already
  seeded in `001_schema.sql` (`OPERATIONS`, `SALES AND MARKETING`,
  `FINANCE`, etc.), since those may already be referenced by FK from
  employees/designations. Reconciling the two sets — repointing any
  existing rows and deleting the placeholders — is a one-off data cleanup
  left for you to run once you know what's already assigned, not baked
  into this migration.
- **Designations**, mapped to the new departments by name.
  `CONSTRUCTION WORKER` / `CONSTRUCTION WORKER-CUM-DRIVER` appear under
  both Inspection and Operation in the doc, but `designations` is a flat
  unique-name table (one designation → one department), so both currently
  resolve to Inspection and the Operation insert is a no-op. See the
  comment in the migration for two ways to resolve this if it matters for
  your reporting.
- **Shifts**, one row per area/day-type (Office weekday x2 timing
  options, Office Saturday, Operation Site weekday/Saturday, Inspection
  Site weekday/Saturday, Work Shop weekday/Saturday) — 9 rows total,
  matching the exact hours in the doc.
- Noted but **not** migrated: the `shifts` table only stores a single
  `break_duration`, not a lunch *window*. Office lunch is flexible (any
  1 hour between 11:30am-2:00pm) while Site lunch is fixed (12-1pm) — if
  you want to enforce/report against the window itself rather than just
  the duration, that needs two new columns on `shifts`
  (`lunch_window_start`, `lunch_window_end`). Left as a schema decision
  for you rather than assumed.

All inserts use `ON CONFLICT DO NOTHING` against the unique constraints
already on `departments.department_name` / `designations.designation_name`,
so the file is safe to re-run.

## Module 1 of N: Payroll — security fix + repository/RBAC/audit pattern

This is the first "one module at a time" iteration from the Frontend
Readiness Report's Critical findings: Payroll had no permission check on
any route, and — separately, found while doing this pass — the service
layer was actually broken.

**Files Modified**
- `app/payroll/services.py` (rewritten)
- `app/payroll/routes.py` (rewritten)
- `app/core/rbac.py` (added `get_role_name`, `has_permission`)
- `app/core/helpers/employee_helper.py` (added `get_employee_id_for_auth_user`)
- `sql/004_payroll_permissions_seed.sql` (new)

**Reason**
1. *Security*: every payroll route (`GET/POST/PUT/DELETE /payroll/...`)
   only checked `get_current_user` — any authenticated employee could
   read or modify any other employee's salary record. This was the
   top Critical item from the Frontend Readiness Report.
2. *Correctness bug found during the fix*: the original
   `app/payroll/services.py` called `success_response(...)` and
   referenced `EMPLOYEE_CREATED` in every function, but neither was
   imported anywhere in the file. `create_payroll` and `update_payroll`
   also did `success_response(...)[0]` — `success_response` returns a
   dict, so indexing it with `[0]` raises `KeyError: 0`. In practice
   this meant `create_payroll` and `update_payroll` would throw
   `NameError` before ever reaching the Supabase call — payroll
   generation and updates were non-functional, not just insecure. Fixed
   as part of this pass since it's the same file.

**Database Changes**
None to existing tables. `sql/004_payroll_permissions_seed.sql` only
inserts rows (4 new permissions + role_permissions assignments), no
schema/DDL changes.

**API Changes**
- `POST /payroll` — now requires `CREATE_PAYROLL`.
- `GET /payroll` — now requires `VIEW_PAYROLL` (company-wide list; HR/Admin only).
- `PUT /payroll/{id}` — now requires `EDIT_PAYROLL`.
- `DELETE /payroll/{id}` — now requires `DELETE_PAYROLL`.
- `GET /payroll/{id}` — still any authenticated user, but the service now
  checks `VIEW_PAYROLL` OR that the record belongs to the caller; anyone
  else gets a 403 instead of the record.
- `GET /payroll/my` — **new, additive** endpoint. Self-service list of
  the caller's own payroll records, no special permission required
  beyond being logged in. Nothing existing depends on this route, so
  it's not a breaking change.
- `GET /payroll` response shape changed from a bare list to
  `{records, total, page, limit}` to support pagination (it accepted no
  `page`/`limit` params before and returned everything). **This is a
  breaking change for any existing frontend code reading `/payroll` as
  a flat array** — see below.

**Permission Changes**
Added `CREATE_PAYROLL`, `VIEW_PAYROLL`, `EDIT_PAYROLL`, `DELETE_PAYROLL`.
Granted to `HR ADMIN` (all four) and `HR EXECUTIVE` (all but delete).
Deliberately not granted to Manager/Employee/Viewer roles — employees see
their own payslips via the ownership check on `GET /payroll/{id}` and the
new `/payroll/my`, not via the broad `VIEW_PAYROLL` permission. `SUPER
ADMIN` bypasses permission checks entirely (existing behavior in
`core/rbac.py`, unchanged).

**Migration Changes**
Run `sql/004_payroll_permissions_seed.sql` after `001`/`002`/`003`. Idempotent
(`ON CONFLICT DO NOTHING` throughout), safe to re-run.

**Breaking Changes**
- `GET /payroll` response shape (flat list → `{records, total, page, limit}`).
- Any client currently relying on `GET/PUT/DELETE /payroll/...` working
  for *any* logged-in user (not just HR/Admin) will now get a 403 unless
  their role has been granted the relevant permission via
  `sql/004_payroll_permissions_seed.sql`.

**Testing Performed**
`python3 -m py_compile` on all four modified Python files — syntax-valid.
I do not have a running Supabase instance or test database in this
environment, so this has **not** been exercised against a live database
or with an actual FastAPI test client. Before deploying: run the new
migration, then manually verify (a) an EMPLOYEE-role user can hit
`/payroll/my` and their own `/payroll/{id}` but gets 403 on `/payroll`
and other employees' records, and (b) an HR ADMIN user can still do
everything the old unrestricted routes could.

---

Next candidates from the Critical list (not started, waiting for your
go-ahead on which one): Leave approval (`PUT /leaves/{id}` doesn't check
`APPROVE_LEAVE`), Documents (`GET /documents/employee/{id}` has no
ownership/role check), Audit Logs (`GET /audit-logs` readable by any
authenticated user, should likely be HR/Admin-only).

## Module 2 of N: Leave approval — security fix + repository/RBAC/audit pattern

Second "one module at a time" iteration, following the Payroll pass.

**Files Modified**
- `app/leaves/services.py` (rewritten)
- `app/leaves/routes.py` (rewritten)
- `app/leaves/schemas.py` (rewritten)
- `app/core/helpers/employee_helper.py` (added `get_manager_chain`,
  `is_manager_of`, `get_all_report_ids`)
- `sql/005_leave_permissions_seed.sql` (new)

**Reason**
1. *Security*: no route in this module checked any permission at all —
   `GET /leaves` (every leave request, every employee) and
   `PUT /leaves/{id}` (approve/reject) were reachable by any authenticated
   user, regardless of role.
2. *Correctness bugs found during the fix* (this module didn't just lack
   permission checks — it was non-functional):
   - Every service function called `success_response(...)` and referenced
     `EMPLOYEE_CREATED` without importing either — every route would have
     thrown `NameError` before returning.
   - `apply_leave` and `update_leave_status` did `success_response(...)[0]`
     — `success_response` returns a dict, so `[0]` raises `KeyError`.
   - `supabase_admin.table("leaves")` — **the table doesn't exist.** The
     actual schema (`sql/001_schema.sql`) has `leave_requests`, with
     `leave_type_id` (FK to `leave_types`) instead of a free-text
     `leave_type`, and `start_date`/`end_date` instead of
     `from_date`/`to_date`. Every call would have failed against a real
     database regardless of the bugs above.
   - `routes.py` read `user.employee_id` — `get_current_user` returns the
     raw Supabase auth user, which has no `employee_id` attribute; this
     also would have raised on every request. Replaced with the existing
     `get_employee_id_for_auth_user()` lookup (same pattern as Payroll).

**Database Changes**
None to existing tables. `sql/005_leave_permissions_seed.sql` only inserts
rows (1 new permission + role_permissions assignments).

**API Changes**
- `POST /leaves/` — request body unchanged (`leave_type` name string,
  `from_date`, `to_date`, `reason`); now actually inserts into
  `leave_requests` (resolving `leave_type` to `leave_type_id` against
  `leave_types`) instead of failing.
- `GET /leaves/my` — fixed to return the full list of the caller's leave
  requests (previously returned a single record via a busted
  `data[0]` and would have errored anyway).
- `GET /leaves/` — now requires `VIEW_LEAVE_REQUESTS` (HR/Admin,
  company-wide); response shape changed to `{records, total, page,
  limit}` with new optional `page`/`limit`/`status` query params, same
  pagination convention as `GET /payroll`.
- `GET /leaves/team` — **new, additive** endpoint. Returns leave requests
  from the caller's direct + indirect reports only, for managers who
  don't have company-wide `VIEW_LEAVE_REQUESTS`.
- `PUT /leaves/{id}` — request body changed from a bare `status` query
  param to a JSON body (`{"status": "Approved" | "Rejected", "comments":
  "..."}`); now requires `APPROVE_LEAVE`, and the service additionally
  enforces that the caller is either the requesting employee's direct/
  indirect manager or holds company-wide `VIEW_LEAVE_REQUESTS` — a
  Manager can no longer approve/reject another manager's team's leave.
  Also rejects re-processing an already-approved/rejected request, and
  blocks self-approval. Every approval/rejection now also writes a row to
  `leave_approval_history` (existing table, previously unused) in
  addition to the general audit log.

**Permission Changes**
Added `VIEW_LEAVE_REQUESTS`, granted to `HR ADMIN` and `HR EXECUTIVE`.
Reused the existing `APPROVE_LEAVE` permission (already seeded for
`HR ADMIN`, `MANAGER`, `OPERATIONS MANAGER` in
`sql/002_role_permissions_seed.sql`) for the approve/reject route, now
combined with the manager-chain ownership check described above so it's
scoped correctly per role rather than being all-or-nothing.

**Migration Changes**
Run `sql/005_leave_permissions_seed.sql` after `001`–`004`. Idempotent
(`ON CONFLICT DO NOTHING` throughout), safe to re-run.

**Breaking Changes**
- `GET /leaves/` response shape (was broken before; now
  `{records, total, page, limit}`).
- `GET /leaves/my` now returns a list instead of a single (buggy) record.
- `PUT /leaves/{id}` now takes a JSON body instead of a `status` query
  param, and requires `APPROVE_LEAVE` + manager/HR ownership instead of
  being open to any authenticated user.
- None of the above previously worked end-to-end against a real database,
  so there's no working client behavior this actually changes in
  practice — but any frontend code written *against the intended
  contract* of the old routes will need to match the new shapes.

**Testing Performed**
`python3 -m py_compile` on all modified/added Python files, plus a full
`app/` tree compile to confirm nothing else was broken — syntax-valid. No
running Supabase/database instance is available in this environment, so
this has **not** been exercised against a live database or FastAPI test
client. Before deploying: run the new migration, then manually verify
(a) an EMPLOYEE can `POST /leaves/`, see it on `/leaves/my`, but gets 403
on `/leaves/`, `/leaves/team`, and `PUT /leaves/{id}`; (b) a MANAGER can
approve/reject a direct report's leave via `PUT /leaves/{id}` and see it
on `/leaves/team`, but gets 403 approving a leave request from an
employee outside their reporting chain; (c) an HR ADMIN can see and
approve/reject anything.

**Known related issue found, not fixed in this pass (out of scope)**
`app/dashboard/services.py` and `app/reports/services.py` also call
`supabase_admin.table("leaves")` directly — the same nonexistent-table
bug this pass fixed in the Leave module itself. Left alone since Dashboard
and Reports are their own phases in your list; flagging so it isn't
mistaken for already-fixed.

## Module 3 of N: Documents — access control + repository/RBAC/audit pattern

Third "one module at a time" iteration.

**Files Modified**
- `app/documents/services.py` (rewritten)
- `app/documents/routes.py` (rewritten)
- `sql/006_document_permissions_seed.sql` (new)

`app/documents/schemas.py` was not touched — the existing request/response
shapes were already correct.

**Reason**
*Security only* — unlike Leave, this module's Supabase calls actually
worked (table name and columns matched the schema). The problem was purely
missing authorization, called out explicitly in the earlier Frontend
Readiness Report finding: `GET /documents/employee/{id}` (and every other
route in the module) had no ownership or role check — any authenticated
user could list, read, update, or delete *any* employee's documents,
including confidential ones (ID proofs, contracts, PAN/Aadhaar copies).

**Database Changes**
None to existing tables. `sql/006_document_permissions_seed.sql` only
inserts rows (4 new permissions + role_permissions assignments).

**API Changes**
- `POST /documents/` — now requires `CREATE_DOCUMENT`.
- `GET /documents/` — now requires `VIEW_DOCUMENTS` (HR/Admin,
  company-wide); response shape changed from a bare list to
  `{records, total, page, limit}` with new `page`/`limit` query params,
  same pagination convention as `GET /payroll` and `GET /leaves/`.
- `GET /documents/my` — **new, additive** endpoint. Self-service list of
  the caller's own documents.
- `GET /documents/employee/{employee_id}` — now requires either
  `VIEW_DOCUMENTS` or that `employee_id` is the caller's own; anyone else
  gets 403 instead of another employee's document list.
- `GET /documents/{document_id}` — same ownership rule as above, applied
  to a single record.
- `PUT /documents/{document_id}` — now requires `EDIT_DOCUMENT`.
- `DELETE /documents/{document_id}` — now requires `DELETE_DOCUMENT`.

**Permission Changes**
Added `CREATE_DOCUMENT`, `VIEW_DOCUMENTS`, `EDIT_DOCUMENT`,
`DELETE_DOCUMENT`. Granted to `HR ADMIN` (all four) and `HR EXECUTIVE`
(all but delete) — same split as Payroll. Deliberately **not** granted to
`MANAGER` / `OPERATIONS MANAGER` / `INSPECTION MANAGER`: employee
documents are treated as confidential by default and scoped to
HR/Admin + the owning employee only, not opened up to the reporting-
manager hierarchy the way Leave approval is. If the business wants
managers to see some document types (e.g. certifications) but not others
(e.g. ID proofs), that needs a `document_type`-level permission split,
which the current schema doesn't support — flagging as a design decision
for you to confirm rather than assuming it.

**Migration Changes**
Run `sql/006_document_permissions_seed.sql` after `001`–`005`. Idempotent
(`ON CONFLICT DO NOTHING` throughout), safe to re-run.

**Breaking Changes**
- `GET /documents/` response shape (flat list → `{records, total, page,
  limit}`).
- Any client currently relying on `GET/PUT/DELETE /documents/...` or
  `GET /documents/employee/{id}` working for *any* logged-in user will
  now get 403 unless their role has been granted the relevant permission,
  or the record is their own.

**Testing Performed**
`python3 -m py_compile` on all modified files, plus a full `app/` tree
compile — syntax-valid. No running Supabase instance available in this
environment, so not exercised against a live database. Before deploying:
run the new migration, then manually verify (a) an EMPLOYEE can hit
`/documents/my` and their own `/documents/{id}` /
`/documents/employee/{own_id}`, but gets 403 on another employee's
documents and on `/documents/`; (b) an HR ADMIN can still do everything
the old unrestricted routes could.

## Module 4 of N: Audit Logs — access control + a core audit-pipeline bug fix

Fourth "one module at a time" iteration.

**Files Modified**
- `app/audit_logs/services.py` (rewritten)
- `app/audit_logs/routes.py` (rewritten)
- `app/core/audit.py` (bug fix, see below — shared file, not a full rewrite)
- `sql/007_audit_log_permissions_seed.sql` (new)

**Reason**

1. *Security*: identical shape to the Documents finding — every route
   (`GET /audit-logs`, `GET /audit-logs/{id}`, the employee/module/
   action/date filters, and even `DELETE /audit-logs/{id}`) only checked
   `get_current_user`. Any authenticated user could read the entire audit
   trail — who changed what, on any employee's payroll/leave/document
   record — and could delete any entry outright, which defeats the point
   of an audit trail (no non-repudiation if anyone can erase it).

2. *A real bug found while verifying this module, affecting Payroll,
   Leaves, and Documents from the previous three passes*: `audit_logs.
   employee_id` is a foreign key to `employees(id)` (see
   `sql/001_schema.sql`), but `record_audit_log()` was being called with
   `performed_by=current_user.id` / `user.id` — the **Supabase auth user
   id**, not an `employees.id`. Those are different id spaces (the link
   between them is `user_profiles.auth_user_id → user_profiles.
   employee_id`). Every audit insert from Payroll, Leaves, and Documents
   was therefore violating the FK, failing, and — because
   `record_audit_log()` is designed to "never raise" so a logging failure
   can't break the request — failing *silently*. The audit trail for
   those three modules has not actually been recording anything.

   Fixed at the single shared source (`app/core/audit.py`), not by
   touching the three already-shipped call sites: `record_audit_log` now
   resolves `performed_by` to a real `employees.id` via the existing
   `get_employee_id_for_auth_user()` lookup before inserting. If it
   doesn't resolve (e.g. a caller already passes an `employees.id`
   directly), the original value is used as-is, so this is additive, not
   a behavior change for any caller that was already correct.
   `record_audit_log()` also now returns the inserted row instead of
   nothing, since the Audit Logs module's own manual-create endpoint
   needs it back.

**Database Changes**
None to existing tables. `sql/007_audit_log_permissions_seed.sql` only
inserts rows (2 new permissions + one role_permissions assignment).

**API Changes**
- `GET /audit-logs/`, `/employee/{id}`, `/module/{module}`,
  `/action/{action}`, `/date/{date}`, `/{log_id}` — all now require
  `VIEW_AUDIT_LOGS`. The list-style endpoints also gained `page`/`limit`
  query params and now return `{records, total, page, limit}` instead of
  an unbounded flat list (audit logs grow indefinitely; the old
  `get_audit_logs()` had no pagination at all).
- `POST /audit-logs/` (manual/system log entry) — now requires
  `MANAGE_AUDIT_LOGS` and is routed through `record_audit_log()` instead
  of a separate raw insert, fixing the same FK bug for this path and
  removing a duplicate write implementation.
- `DELETE /audit-logs/{log_id}` — now requires `MANAGE_AUDIT_LOGS`, and
  the deletion itself is now recorded as a new audit log entry
  (module `AUDIT_LOGS`, action `DELETE`) so removing a log leaves a
  trace of who did it.

**Permission Changes**
Added `VIEW_AUDIT_LOGS` (granted to `HR ADMIN`) and `MANAGE_AUDIT_LOGS`
(deliberately granted to **no role** in the seed — `SUPER ADMIN` bypasses
`require_permission` entirely per `app/core/rbac.py`, so this makes
manual log creation and deletion Super-Admin-only by design, not by
oversight. Reading the trail is extended to HR ADMIN; tampering with it
is not, even for HR ADMIN).

**Migration Changes**
Run `sql/007_audit_log_permissions_seed.sql` after `001`–`006`.
Idempotent, safe to re-run.

**Breaking Changes**
- All read endpoints now require `VIEW_AUDIT_LOGS` — any client relying
  on any authenticated user reading the audit trail will get 403.
- `GET /audit-logs/`, `/employee/{id}`, `/module/{module}`,
  `/action/{action}` response shape changed from a flat list to
  `{records, total, page, limit}`.
- `POST /audit-logs/` and `DELETE /audit-logs/{id}` now require
  `MANAGE_AUDIT_LOGS` (Super Admin only) instead of being open to any
  authenticated user.
- Retroactive note, not a change from this pass: Payroll, Leave, and
  Document audit rows written *before* this fix were silently dropped
  due to the FK bug above — there is no historical data to migrate,
  because it was never written.

**Testing Performed**
`python3 -m py_compile` on all modified files plus a full `app/` tree
compile — syntax-valid. No running Supabase instance available in this
environment. Before deploying: run the new migration, then manually
verify (a) a non-HR employee gets 403 on every `/audit-logs/*` route;
(b) an HR ADMIN can read but gets 403 on `POST`/`DELETE`; (c) a SUPER
ADMIN can do everything; (d) after the fix, triggering a Payroll/Leave/
Document create or update actually produces a row in `audit_logs` (this
is the regression test for the FK bug — check `employee_id` on the new
row matches a real `employees.id`, not an auth user id).

## Module 5 of N: Attendance — completion + security + a schema-mismatch bug fix

Fifth "one module at a time" iteration. This one was a full build-out, not
just a security pass — the module only had check-in/check-out/my before.

**Files Modified**
- `app/attendance/services.py` (rewritten)
- `app/attendance/routes.py` (rewritten)
- `app/attendance/schemas.py` (rewritten)
- `sql/008_attendance_schema_additions.sql` (new — see Database Changes)
- `sql/009_attendance_permissions_seed.sql` (new)

**Reason**

1. *Security*: identical shape to Attendance's siblings before this pass —
   every route (including `GET /attendance/my`) read `user.employee_id`,
   which doesn't exist on the Supabase auth user object (same class of
   bug Leave had). Every request would have thrown before doing anything.
   Beyond that, there were no permission or ownership checks at all.

2. *Another schema-mismatch bug found*, same category as Leave's wrong
   table name: the original check-in/check-out code wrote to
   `check_in_lat` / `check_in_long` / `check_out_lat` / `check_out_long` —
   **none of those columns exist** in `sql/001_schema.sql`, under any
   name. Every check-in/check-out call would have failed against a real
   database. Added as `check_in_latitude` / `check_in_longitude` /
   `check_out_latitude` / `check_out_longitude` in the new migration
   (matching the naming already used on `locations.latitude/longitude`).

3. *Everything else in the spec's Attendance list that wasn't built yet*:
   breaks, regularization, analytics, shift/policy-driven calculations,
   geofencing, device/browser tracking, team and company-wide views.

**Database Changes** (`sql/008_attendance_schema_additions.sql`)
- Added `check_in_latitude`, `check_in_longitude`, `check_out_latitude`,
  `check_out_longitude` (`double precision`, nullable) to `attendance` —
  fixes the bug above.
- Added `ip_address`, `device_info` (`text`, nullable) to `attendance` —
  "Device Tracking" / "Browser Tracking" from the spec, captured from the
  request at check-in, same approach `app/core/audit.py` already uses.
- All additive/nullable — no existing row or query is affected.

**API Changes**
- `POST /attendance/check-in` — now resolves the employee correctly (was
  broken), validates an optional `location_id` against `locations`
  (Haversine distance check against that location's `radius`, only if
  both are configured — "Geo Location Ready"), computes `late_minutes`
  against the employee's **resolved shift** (`employee_shift_history` →
  `employees.shift_id`, with a Saturday-variant lookup — see the code
  comment in `_get_employee_shift` for the exact heuristic and its
  limits) + `attendance_rules` grace period, and records IP/user-agent.
- `POST /attendance/check-out` — now computes `working_minutes` net of
  actual break time (previously breaks weren't tracked at all),
  `early_checkout_minutes`, `overtime_minutes`, and a `Half Day` status,
  all against the resolved shift's `working_hours` (or the fallback
  `attendance_rules` if no shift is resolved) instead of a hardcoded
  9-hour day.
- `POST /attendance/break-start`, `POST /attendance/break-end` — **new**.
  Multiple breaks per day, writing to `attendance_breaks` (existed in the
  schema, unused before); rejects starting a second concurrent break or
  ending one that isn't open.
- `GET /attendance/my` — fixed (broken before), added optional
  `from_date`/`to_date` filters.
- `GET /attendance/timeline/{date}` — **new**. One day's record plus its
  breaks, for a day-view UI.
- `POST /attendance/regularization`, `GET /attendance/regularization/my`,
  `GET /attendance/regularization/team`,
  `PUT /attendance/regularization/{id}` — **new**. Submit/list/approve
  workflow on `attendance_corrections` (existed, unused before), with the
  same manager-chain-or-HR ownership model as Leave approval. Approving a
  request also patches the underlying `attendance` row's times if one
  exists.
- `GET /attendance/team` — **new**. Today's (or a given date's) status
  for the caller's direct + indirect reports.
- `GET /attendance/` — **new**. Company-wide, paginated, requires
  `VIEW_ALL_ATTENDANCE`.
- `GET /attendance/employee/{employee_id}` — **new**. HR/Admin via
  `VIEW_ALL_ATTENDANCE`, or the employee viewing their own.
- `GET /attendance/analytics` — **new**. Date-range aggregate counts
  (present/half-day/late, average working minutes, total overtime),
  requires `VIEW_ALL_ATTENDANCE`.
- `PUT /attendance/{attendance_id}` — **new**. Direct HR/Admin correction
  of a record, requires `EDIT_ATTENDANCE` (a permission that already
  existed in the seed but had nothing using it until now).

**Permission Changes**
Added `VIEW_ALL_ATTENDANCE` (HR ADMIN, HR EXECUTIVE — company-wide scope,
distinct from the already-broad `VIEW_ATTENDANCE`) and
`APPROVE_ATTENDANCE_CORRECTION` (HR ADMIN, MANAGER, OPERATIONS MANAGER —
mirrors `APPROVE_LEAVE`'s distribution exactly). Reused the existing
`VIEW_ATTENDANCE` (self/team-scoped) and `EDIT_ATTENDANCE` (HR-tier direct
edit) permissions, which were already seeded but had no endpoints
enforcing or using them before this pass.

**Migration Changes**
Run `sql/008_attendance_schema_additions.sql` then
`sql/009_attendance_permissions_seed.sql` after `001`–`007`. Both
idempotent, safe to re-run.

**Breaking Changes**
- Every route now requires either a valid linked employee profile
  (self-service routes) or a specific permission (HR/Admin routes) —
  previously nothing worked at all due to the `user.employee_id` bug, so
  there's no currently-working client behavior this changes in practice.
- `check_in_lat`/`check_in_long`/`check_out_lat`/`check_out_long` were
  never real columns; any frontend code written against those exact names
  needs to use the new `check_in_latitude` etc. names instead.

**Design decisions flagging for your review**
- Shift assignment isn't day-of-week aware in the schema (an employee has
  one `shift_id`, not a weekday-vs-Saturday pair), but the real seeded
  shift data (`sql/003_attendance_info_seed.sql`) models Saturday hours
  as a *separate* shift row per area (e.g. "OFFICE - WEEKDAY (9:00-6:00)"
  vs "OFFICE - SATURDAY"). I bridged this with a naming-convention lookup
  (strip everything before " - ", look for a "<area> ... SATURDAY" shift)
  rather than a schema change — works with the data as seeded, but it's a
  heuristic, not a first-class model. If you want it modeled properly,
  that's a `employee_shift_history`-style table keyed by day-of-week
  instead of a single `shift_id`.
- No automatic "Absent" marking for employees who never check in at all —
  that needs a scheduled job (there's no background-worker mechanism in
  this codebase yet), not something a synchronous request-handling API
  can do on its own. Flagging as a gap rather than building a scheduler
  into this pass.
- Biometric device integration (`attendance_devices`,
  `employee_biometrics`, `biometric_logs`, `biometric_device_tokens`
  tables already exist in the schema) is untouched — a distinct
  subsystem, out of scope here.

**Testing Performed**
`python3 -m py_compile` on all modified/added files plus a full `app/`
tree compile — syntax-valid. No running Supabase instance available in
this environment. Before deploying: run both new migrations, then
manually verify (a) check-in/out actually succeeds now (it didn't
before — confirm the new geo columns exist first); (b) an employee with
a shift assigned gets a sensible `late_minutes` relative to that shift's
`start_time` + `grace_period`, not a hardcoded 9am; (c) breaks reduce
`working_minutes` at checkout; (d) a manager can approve a direct
report's regularization request via `/attendance/regularization/{id}` but
gets 403 on someone outside their reporting chain; (e) `VIEW_ALL_ATTENDANCE`
holders can hit `/attendance/` and `/attendance/analytics`, others get 403.

## Suggested order for the next pass
1. Run `sql/001_schema.sql` then `sql/002_role_permissions_seed.sql`.
2. Roll the `employees/` pattern (repository + `require_permission` +
   `record_audit_log`) out to `attendance`, `leaves`, `overtime`, and
   `payroll` — these are the highest-value, most-audited modules.
3. Add Branch/Team tables + org hierarchy.
4. Add the missing employee sub-tables (bank, skills, certifications,
   assets) and lock them behind their own permissions (`VIEW_BANK_DETAILS`
   etc.) so "My Team" view can safely never touch them.
5. Build Timesheets and the Salary Structure scaffolding (tables + schemas
   only, per the brief).

## Auth core: GET /auth/me + dynamic sidebar + role redirect

**Files added**
- `sql/010_auth_me_sidebar.sql` — `roles.redirect_path` column + new `modules` table (label/icon/route/sort_order per sidebar entry, `always_visible` flag for Dashboard/Profile).
- `app/core/sidebar.py` — builds a role's sidebar from `role_permissions` → `permissions.module` → `modules`, purely data-driven. SUPER ADMIN gets every module (matches its implicit-all-permissions behavior in `app/core/rbac.py`).

**Files changed**
- `app/core/rbac.py` — added `get_permissions_for_role()` (flat list of permission names for a role; expands to every permission for SUPER ADMIN).
- `app/auth/schemas.py` — added `MeResponse`/`MeEnvelope`/`SidebarItem`/`MeProfile`; removed a duplicate import.
- `app/auth/services.py` — added `get_me(auth_user)`: one query for profile+role+employee+department+designation, then permissions + sidebar + redirect_path. Also added a best-effort `LOGIN` audit log call in `login_user` (was previously not logged at all, despite the "log every login" requirement).
- `app/auth/routes.py` — added `GET /auth/me`.
- `app/roles/services.py` — unrelated bug fix found while in this area: `get_roles()`/`get_role_by_id()` referenced an undefined `EMPLOYEE_CREATED` message and undefined `success_response`, and indexed `response.data[0]` on a list-of-all-roles query — every call to `GET /roles` or `GET /roles/{id}` would have thrown a 500 or `NameError`. Rewritten to use the existing `success_response` helper correctly.

**API**
`GET /auth/me` (requires a valid bearer token) returns:
```json
{
  "success": true,
  "message": "User profile fetched successfully.",
  "data": {
    "id": "...", "name": "...", "email": "...",
    "role": "HR ADMIN", "role_id": "...",
    "organization": null, "branch": null,
    "department": { "id": "...", "department_name": "..." },
    "permissions": ["CREATE_EMPLOYEE", "VIEW_EMPLOYEE", ...],
    "allowed_modules": ["DASHBOARD", "EMPLOYEE", "ATTENDANCE", ...],
    "sidebar": [{ "key": "DASHBOARD", "label": "Dashboard", "icon": "LayoutDashboard", "route": "/dashboard" }, ...],
    "redirect_path": "/hr",
    "theme": "light",
    "profile": { "employee_id": "AKR-12345", "full_name": "...", ... }
  }
}
```
Frontend flow: `POST /auth/login` → store tokens → `GET /auth/me` → `router.push(data.redirect_path)`, render `data.sidebar`. No role branching needed client-side.

**Deliberately returned as `null` for now**
`organization` and `branch` — there is no multi-company schema yet (see "What's deliberately not done" above). Returning the keys now (rather than omitting them) means the frontend contract doesn't change shape once that lands; they just start getting populated. That's the natural next phase.

**Migration order**
Run `sql/010_auth_me_sidebar.sql` after `001`–`009`. Additive/idempotent (`on conflict do nothing`, `add column if not exists`) — safe to re-run, no existing data affected.

**Testing performed**
`python3 -m py_compile` across the full `app/` tree — syntax-valid. No live Supabase instance available here to hit the endpoint end-to-end; before deploying, verify: (a) `GET /auth/me` for a SUPER ADMIN returns every module in `sidebar`; (b) for HR ADMIN/EMPLOYEE it returns only modules matching their seeded `role_permissions` plus Dashboard/Profile; (c) `redirect_path` matches what's set in `sql/010_auth_me_sidebar.sql` for that role; (d) a login now produces a row in `audit_logs` with `module='AUTH', action='LOGIN'`.

**Next up**, per the original priority list — the two biggest remaining pieces of the brief:
1. Organization/Branch/Team tables + query-level isolation (multi-company).
2. Policy engine (own-team/own-branch/own-data row-level filtering) layered on top of today's role/permission checks.
