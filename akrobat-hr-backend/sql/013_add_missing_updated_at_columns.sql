-- =====================================
-- ADD MISSING updated_at COLUMNS
-- =====================================
-- app/core/repository.py's SupabaseRepository.update() stamps every
-- update payload with `updated_at` unconditionally. That's fine for most
-- tables, but a few never got the column in 001_schema.sql, so any
-- `.update()` call against them fails with:
--   "Could not find the 'updated_at' column of '<table>' in the schema
--   cache" (PGRST204)
--
-- leave_requests hits this now that PUT /leaves/{id} (approve/reject) is
-- wired up. documents has the same gap and will hit it the next time a
-- document is edited (see document_repo.update() in
-- app/documents/services.py). leave_types and attendance_corrections are
-- also missing it but nothing calls .update() on them today — added here
-- too so they don't bite later.
--
-- Safe to re-run.

alter table leave_requests add column if not exists updated_at timestamp default now();
alter table documents add column if not exists updated_at timestamptz default now();
alter table leave_types add column if not exists updated_at timestamp default now();
alter table attendance_corrections add column if not exists updated_at timestamp default now();

-- Backfill existing rows so updated_at isn't null for records written
-- before this column existed.
update leave_requests set updated_at = coalesce(applied_date, now()) where updated_at is null;
update documents set updated_at = coalesce(created_at, now()) where updated_at is null;
update leave_types set updated_at = coalesce(created_at, now()) where updated_at is null;
update attendance_corrections set updated_at = coalesce(created_at, now()) where updated_at is null;
