-- =====================================================================
-- SESSION INVALIDATIONS -- backing table for "Force logout all"
-- =====================================================================
-- app/access_control/services.py (invalidate_sessions, is_session_invalidated,
-- clear_session_invalidation) and app/core/security.py::get_current_user
-- already read/write this table -- it was simply never created, which is
-- why /auth/me and /auth/refresh both 401'd with "Invalid or expired
-- token." on every login (their broad except swallowed the underlying
-- "relation does not exist" error and reported it as a bad token instead).
--
-- One row = one auth user is currently force-logged-out. Presence of the
-- row is the only thing that matters (see is_session_invalidated) -- the
-- timestamp is kept for auditing ("since when"), not compared against.
-- Removed entirely by a fresh, real login (login_user ->
-- clear_session_invalidation), which is the one thing that should lift
-- a force logout for that user.
-- =====================================================================

create table if not exists session_invalidations (
    auth_user_id uuid primary key,
    invalidated_after timestamptz not null default now()
);