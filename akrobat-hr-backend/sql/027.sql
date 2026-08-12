-- =====================================================================
-- 027_enable_rls.sql
--
-- WHY THIS EXISTS
-- ----------------
-- Every query in this codebase goes through `supabase_admin`
-- (app/core/database.py), which authenticates to Supabase with the
-- SERVICE ROLE key. Postgres Row Level Security never applies to the
-- service_role -- it always bypasses RLS, policies or not. So this
-- migration changes NOTHING about how the app behaves today.
--
-- What it protects against instead: the ANON key. Right now nothing
-- uses it directly (the frontend only talks to this FastAPI backend,
-- not Supabase), but the anon key is still present in .env and could
-- end up in a future feature, a leaked env var, or a browser devtools
-- inspection. Without RLS, a table with RLS disabled is fully open to
-- anyone holding that key -- they could read/write every row directly
-- against Supabase's REST API, completely bypassing your FastAPI
-- permission checks. This migration is a database-level backstop, not
-- something needed for the app's current behavior to work correctly.
--
-- DESIGN
-- ------
-- Deny-by-default: enable RLS on every application table and add ONE
-- policy per table that allows service_role only. No anon/authenticated
-- policies are defined, so with RLS enabled and no matching policy,
-- Postgres denies those roles by default -- exactly what we want, since
-- all real access control already lives in the FastAPI layer
-- (app/core/rbac.py, app/core/permissions.py) and per-endpoint ownership
-- checks (e.g. app/payroll/services.get_payroll).
--
-- HOW TO RUN
-- ----------
-- Supabase Dashboard -> SQL Editor -> paste this file -> Run.
-- Safe to re-run (each block uses IF NOT EXISTS / drops-then-creates).
-- =====================================================================

do $$
declare
    tbl text;
    tables text[] := array[
        'roles', 'permissions', 'role_permissions',
        'departments', 'designations', 'shifts',
        'employees', 'employee_documents', 'user_profiles', 'audit_logs',
        'attendance', 'attendance_breaks', 'attendance_corrections',
        'attendance_rules', 'employee_shift_history',
        'locations', 'projects', 'project_assignments',
        'project_workload', 'project_status_history',
        'payroll', 'documents', 'employee_project_assignments'
    ];
begin
    foreach tbl in array tables
    loop
        -- Only touch tables that actually exist in this database --
        -- some deployments may not have every table (e.g. optional
        -- modules), so this skips anything not present instead of
        -- erroring out the whole migration.
        if exists (
            select 1 from information_schema.tables
            where table_schema = 'public' and table_name = tbl
        ) then
            execute format('alter table public.%I enable row level security;', tbl);

            -- Drop-then-create so this migration is safe to re-run.
            execute format('drop policy if exists service_role_only on public.%I;', tbl);
            execute format(
                'create policy service_role_only on public.%I
                    for all
                    to service_role
                    using (true)
                    with check (true);',
                tbl
            );
        end if;
    end loop;
end $$;

-- =====================================================================
-- Verify: run this after the block above to confirm every table shows
-- rowsecurity = true, and that a service_role_only policy exists.
-- =====================================================================
-- select tablename, rowsecurity
-- from pg_tables
-- where schemaname = 'public'
-- order by tablename;
--
-- select schemaname, tablename, policyname, roles
-- from pg_policies
-- where schemaname = 'public'
-- order by tablename;