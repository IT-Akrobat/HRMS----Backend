-- =====================================================================
-- SITE VISIT LIVE PRESENCE PINGS
-- =====================================================================
-- Arrive/Depart Site only ever captured a location ONCE, at the moment
-- of arrival/departure — after that, an "on site" employee could be
-- anywhere and the app would never know. This adds a live 1-minute
-- presence ping (POST /attendance/site-visit/ping, called by the
-- frontend while a visit is open):
--   - last_ping_latitude/longitude/at — where + when the employee's
--     device last reported in, refreshed every ~60s while on site.
--   - last_ping_distance_m — distance from that ping to the site's
--     configured lat/lon, using the same haversine math as check-in
--     geofencing (_haversine_meters).
--   - is_outside_radius — true once a ping lands more than the alert
--     radius (500m — see ALERT_RADIUS_M in app/attendance/services.py)
--     from the site. Used as an edge-trigger: a manager/super-admin
--     notification only fires the moment this flips false -> true, not
--     on every single ping while still outside, so being out of range
--     for 20 minutes sends one notification, not twenty.
-- =====================================================================

alter table attendance_site_visits
    add column if not exists last_ping_latitude double precision,
    add column if not exists last_ping_longitude double precision,
    add column if not exists last_ping_at timestamptz,
    add column if not exists last_ping_distance_m double precision,
    add column if not exists is_outside_radius boolean not null default false;

-- Fast "who's currently flagged outside their site radius" lookups, for
-- the manager / super-admin live tracking views.
create index if not exists idx_site_visits_outside_radius
    on attendance_site_visits(employee_id)
    where departure_time is null and is_outside_radius = true;

-- Zeroes out the 10-minute grace period already sitting in existing rows.
-- (The earlier fix to 001_schema.sql / 003_attendance_info_seed.sql only
-- changes what gets INSERTed on a *fresh* database — it does nothing to
-- rows that already exist. This migration updates those rows directly.)

update attendance_rules
set late_grace_minutes = 0;

update shifts
set grace_period = 0;