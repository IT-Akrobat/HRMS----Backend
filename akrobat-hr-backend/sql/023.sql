-- =====================================================================
-- WEB PUSH SUBSCRIPTIONS
-- =====================================================================
-- Backs real browser/OS push notifications (the "notification pops up
-- like WhatsApp, even when the tab is closed" feature). One row per
-- device/browser a user has granted notification permission on -- a
-- user can have several (phone + laptop), so this is keyed by the
-- unique push `endpoint` the browser hands back, not by employee_id
-- alone.
--
-- employee_id matches notifications.user_id's convention elsewhere in
-- this schema (an employees.id, not the raw auth uid).
--
-- p256dh / auth are the subscription's public key + auth secret, both
-- required by the Web Push protocol (RFC 8291) to encrypt the payload
-- so only that browser can read it -- see app/core/push.py.
-- =====================================================================

create table if not exists push_subscriptions (
    id uuid primary key default uuid_generate_v4(),
    employee_id uuid not null references employees(id) on delete cascade,
    endpoint text not null unique,
    p256dh text not null,
    auth text not null,
    user_agent text,
    created_at timestamptz not null default now()
);

create index if not exists idx_push_subscriptions_employee
    on push_subscriptions(employee_id);