-- =====================================================================
-- Fix: "Quantity Surveying" shows no designations, "Operation" shows a
-- duplicate designation
-- Run after 001-024.
-- =====================================================================
--
-- WHAT HAPPENED
-- -------------
-- 1. QUANTITY SURVEYOR / SENIOR QUANTITY SURVEYOR CUM LOGISTICS can end
--    up with a NULL or stale department_id depending on which order
--    003_attendance_info_seed.sql (creates department 'QS') and
--    011_team_leader_and_org_structure.sql (creates a SEPARATE
--    department 'QUANTITY SURVEYING' and points these two designations
--    at it) actually ran in on this environment, and whether
--    016.sql's merge step found both rows to merge. Whichever way it
--    landed, the two designations are re-pointed at the correct QS
--    department below regardless of current state.
--
-- 2. A handful of designations (e.g. CONSTRUCTION WORKER-CUM-DRIVER
--    under OPERATION) ended up with two rows for the same
--    (designation_name, department_id) pair — from before 016.sql's
--    unique-per-department constraint existed, or from a seed file
--    being re-applied with slightly different casing/whitespace, which
--    a naive re-run doesn't catch. This merges any such rows, keeping
--    the oldest one and re-pointing any employee that had been assigned
--    the newer duplicate before deleting it. No employee rows are
--    removed.
--
-- Safe to run more than once.
-- =====================================================================


-- =====================================
-- 1. RE-POINT THE QS DESIGNATIONS AT THE RIGHT DEPARTMENT
-- =====================================

do $$
declare
  qs_id uuid;
begin
  -- Prefer the 'QS' department (short code, from 003_attendance_info_seed.sql).
  select id into qs_id from departments where department_name = 'QS';

  -- Fall back to the older 'QUANTITY SURVEYING' department if 'QS' was
  -- never created on this environment.
  if qs_id is null then
    select id into qs_id from departments where department_name = 'QUANTITY SURVEYING';
  end if;

  if qs_id is not null then
    update designations
    set department_id = qs_id
    where designation_name in ('QUANTITY SURVEYOR', 'SENIOR QUANTITY SURVEYOR CUM LOGISTICS')
      and (department_id is distinct from qs_id);

    -- If both 'QS' and 'QUANTITY SURVEYING' exist, merge the latter into
    -- the former (mirrors 016.sql's merge step, re-run defensively in
    -- case it ran before 'QUANTITY SURVEYING' existed).
    if exists (select 1 from departments where department_name = 'QS')
       and exists (select 1 from departments where department_name = 'QUANTITY SURVEYING') then

      update designations
      set department_id = (select id from departments where department_name = 'QS')
      where department_id = (select id from departments where department_name = 'QUANTITY SURVEYING');

      update employees
      set department_id = (select id from departments where department_name = 'QS')
      where department_id = (select id from departments where department_name = 'QUANTITY SURVEYING');

      delete from departments where department_name = 'QUANTITY SURVEYING';
    end if;
  end if;
end $$;


-- =====================================
-- 2. MERGE DUPLICATE DESIGNATION ROWS
-- =====================================
-- Same designation name (case/whitespace-insensitive) under the same
-- department, kept as one row (the oldest / lowest id). Any employee
-- pointing at a duplicate that's about to be deleted is re-pointed at
-- the surviving row first.

do $$
declare
  dup record;
  keeper_id uuid;
begin
  for dup in
    select
      upper(trim(designation_name)) as norm_name,
      department_id,
      (array_agg(id order by created_at asc, id asc))[1] as keep_id,
      array_remove(array_agg(id order by created_at asc, id asc), (array_agg(id order by created_at asc, id asc))[1]) as drop_ids
    from designations
    group by upper(trim(designation_name)), department_id
    having count(*) > 1
  loop
    keeper_id := dup.keep_id;

    update employees
    set designation_id = keeper_id
    where designation_id = any(dup.drop_ids);

    delete from designations where id = any(dup.drop_ids);
  end loop;
end $$;


-- =====================================================================
-- AFTER RUNNING THIS
-- =====================================================================
-- QS         -> Quantity Surveyor, Senior Quantity Surveyor Cum
--               Logistics                                     [matches doc]
-- OPERATION  -> Project Manager, Construction Worker,
--               Construction Worker-Cum-Driver, Driver,
--               Construction Worker (Storeman)                [5, matches doc, no dupes]
-- =====================================================================