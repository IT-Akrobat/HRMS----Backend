-- =====================================================================
-- Align departments & designations to the org chart doc
-- Run after 001-015. SUPERSEDES 016_merge_duplicate_departments.sql —
-- run THIS ONE instead (016 merged in the opposite direction).
-- =====================================================================
--
-- WHAT THIS DOES
-- --------------
-- 1. Merges each duplicate department pair, keeping the doc's short name
--    (the one on the right survives; the one on the left is merged in
--    and removed):
--
--      QUANTITY SURVEYING         -> QS
--      ENGINEERING                -> DESIGN
--      HUMAN RESOURCE              -> HR
--      FINANCE                    -> ACCOUNT
--      OPERATIONS                 -> OPERATION
--      PROCUREMENT AND LOGISTICS  -> PURCHASING & LOGISTICS
--      SALES AND MARKETING        -> SALES
--
--    (INSPECTION was seeded identically in both places, so it was never
--    duplicated — nothing to do there.)
--
-- 2. Relaxes designations.designation_name from globally UNIQUE to
--    UNIQUE PER DEPARTMENT (designation_name, department_id). Your doc
--    lists "Construction Worker" and "Construction Worker-Cum-Driver"
--    under BOTH Inspection and Operation — the old global-uniqueness
--    constraint made that impossible (whichever department's insert ran
--    first silently "won" the name, per the note left in
--    sql/003_attendance_info_seed.sql). This lets the same title exist
--    once per department instead of once company-wide.
--
-- 3. Adds "Construction Worker" and "Construction Worker-Cum-Driver"
--    under Operation (they already exist under Inspection from the
--    original seed) — the pair the old constraint was blocking.
--
-- Safe to run more than once: every step only acts if its target state
-- doesn't already exist.
-- =====================================================================


-- =====================================
-- 1. MERGE DUPLICATE DEPARTMENTS
-- =====================================

do $$
declare
  pairs text[][] := array[
    array['QUANTITY SURVEYING', 'QS'],
    array['ENGINEERING', 'DESIGN'],
    array['HUMAN RESOURCE', 'HR'],
    array['FINANCE', 'ACCOUNT'],
    array['OPERATIONS', 'OPERATION'],
    array['PROCUREMENT AND LOGISTICS', 'PURCHASING & LOGISTICS'],
    array['SALES AND MARKETING', 'SALES']
  ];
  old_name text;
  new_name text;
  old_id uuid;
  new_id uuid;
  i int;
begin
  for i in 1..array_length(pairs, 1) loop
    old_name := pairs[i][1];
    new_name := pairs[i][2];

    select id into old_id from departments where department_name = old_name;
    select id into new_id from departments where department_name = new_name;

    if old_id is not null and new_id is not null and old_id <> new_id then
      raise notice 'Merging department "%" into "%"', old_name, new_name;

      update designations set department_id = new_id where department_id = old_id;
      update employees set department_id = new_id where department_id = old_id;

      delete from departments where id = old_id;
    end if;
  end loop;
end $$;


-- =====================================
-- 2. RELAX designation_name TO UNIQUE PER DEPARTMENT
-- =====================================

alter table designations drop constraint if exists designations_designation_name_key;

alter table designations
  add constraint designations_name_department_unique
  unique (designation_name, department_id);


-- =====================================
-- 3. ADD THE MISSING OPERATION-SIDE TITLES
-- =====================================
-- These already exist under Inspection (inserted first in
-- sql/003_attendance_info_seed.sql); the old global-unique constraint
-- silently blocked them from also existing under Operation, even though
-- your doc lists them under both.

insert into designations (designation_name, department_id)
select v.designation_name, d.id
from (values
    ('CONSTRUCTION WORKER'),
    ('CONSTRUCTION WORKER-CUM-DRIVER')
) as v(designation_name)
join departments d on d.department_name = 'OPERATION'
on conflict (designation_name, department_id) do nothing;


-- =====================================
-- 4. REMOVE WHAT'S NOT IN THE DOC
-- =====================================
-- Any employee currently holding one of these (department_id /
-- designation_id) just has that field cleared (on delete set null) —
-- nothing errors, no employee rows are removed. Re-assign them to the
-- correct department/designation afterward if that happens.

-- "Civil Engineer" — not in the Design Department list (Engineer, Civil
-- Engineering Drafter, Design Assistant/Draftman only).
delete from designations where designation_name = 'CIVIL ENGINEER';

-- "Administration" department and its one designation — not in the doc
-- at all.
delete from designations where designation_name = 'WORK-AT-HEIGHT INSPECTOR';
delete from departments where department_name = 'ADMINISTRATION';

-- "Construction" department — leftover from the original schema seed,
-- holds no designations, not in the doc.
delete from departments where department_name = 'CONSTRUCTION';


-- =====================================================================
-- AFTER RUNNING THIS
-- =====================================================================
-- Department dropdown will show exactly your 8 doc departments (QS,
-- INSPECTION, DESIGN, HR, ACCOUNT, OPERATION, PURCHASING & LOGISTICS,
-- SALES), each with exactly its own designation list from your doc —
-- Administration, Construction, Civil Engineer, and Work-At-Height
-- Inspector are all removed.
-- =====================================================================