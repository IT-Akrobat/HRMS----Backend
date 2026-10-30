from app.core.database import supabase_admin
from app.core.exceptions import bad_request, internal_server_error
from app.core.helpers.employee_helper import get_employee_id_for_auth_user
from app.core.logger import logger
from app.core.config import VAPID_CLAIMS_EMAIL
from app.core.push import _vapid, push_configured, send_push
from app.core.responses import success_response
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Backs the "Add this device" step of Web Push (see app/core/push.py).
# One row per browser/device a user has granted notification permission
# on -- a user can be subscribed on their phone AND their laptop at once,
# so send_push_to_employee() below fans out to every row, not just one.
# ---------------------------------------------------------------------------


def _resolve_employee_id(auth_user_id: str) -> str:
    employee_id = get_employee_id_for_auth_user(auth_user_id)
    if not employee_id:
        bad_request("No employee record is linked to this account.")
    return employee_id


# =========================
# SUBSCRIBE THIS DEVICE
# =========================


def subscribe(
    auth_user_id: str, endpoint: str, p256dh: str, auth: str, user_agent: str | None
):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        # Upsert on endpoint: a browser reusing/renewing the same
        # subscription (e.g. re-granting permission, or the same device
        # logging in as a different employee later) should replace the
        # old row rather than accumulate duplicates that all fire at once.
        supabase_admin.table("push_subscriptions").upsert(
            {
                "employee_id": employee_id,
                "endpoint": endpoint,
                "p256dh": p256dh,
                "auth": auth,
                "user_agent": user_agent,
            },
            on_conflict="endpoint",
        ).execute()

        return success_response(message="Device subscribed for notifications.")

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to subscribe this device.")


# =========================
# UNSUBSCRIBE THIS DEVICE
# =========================


def unsubscribe(auth_user_id: str, endpoint: str):
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        supabase_admin.table("push_subscriptions").delete().eq("endpoint", endpoint).eq(
            "employee_id", employee_id
        ).execute()

        return success_response(message="Device unsubscribed from notifications.")

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to unsubscribe this device.")


def delete_subscription_by_endpoint(endpoint: str):
    """Used by app/core/push.py to prune a subscription the push service
    has reported as gone (410/404) -- no auth context here since this
    runs from inside a fire-and-forget notification send, not a request."""
    supabase_admin.table("push_subscriptions").delete().eq(
        "endpoint", endpoint
    ).execute()


# =========================
# SEND TO EVERY DEVICE AN EMPLOYEE HAS SUBSCRIBED
# =========================


def send_test_push(auth_user_id: str):
    """
    Diagnostic: sends a real push to every device this employee has
    saved and reports, per device, whether the push service accepted it
    (and the HTTP status / error if not). Does NOT prune anything, so
    it's safe to call repeatedly. Use it to find out *why* closed-app
    notifications don't arrive: no device saved, VAPID not configured,
    or the push service rejecting the key.
    """
    try:
        employee_id = _resolve_employee_id(auth_user_id)

        if not push_configured():
            return success_response(
                message="Push is not configured on the server.",
                data={"configured": False, "devices": 0, "results": []},
            )

        from pywebpush import WebPushException, webpush
        import json

        rows = (
            supabase_admin.table("push_subscriptions")
            .select("endpoint, p256dh, auth, user_agent")
            .eq("employee_id", employee_id)
            .execute()
        )
        results = []
        for row in rows.data or []:
            sub = {
                "endpoint": row["endpoint"],
                "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
            }
            entry = {
                "device": (row.get("user_agent") or "unknown")[:70],
                "push_service": row["endpoint"].split("/")[2],
            }
            try:
                webpush(
                    subscription_info=sub,
                    data=json.dumps(
                        {
                            "title": "Test notification",
                            "body": "Push is working on this device.",
                            "url": "/",
                        }
                    ),
                    vapid_private_key=_vapid,
                    vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
                    ttl=60,
                )
                entry.update(ok=True, status=201)
            except WebPushException as e:
                resp = getattr(e, "response", None)
                entry.update(
                    ok=False,
                    status=getattr(resp, "status_code", None),
                    detail=(getattr(resp, "text", "") or str(e))[:200],
                )
            except Exception as e:  # noqa: BLE001
                entry.update(ok=False, status=None, detail=str(e)[:200])
            results.append(entry)

        return success_response(
            message="Test push attempted.",
            data={"configured": True, "devices": len(results), "results": results},
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.exception(e)
        internal_server_error("Unable to send test notification.")


def send_push_to_employee(employee_id: str, title: str, body: str, url: str = "/"):
    """
    Fire-and-forget, called from
    app/notifications/services.py::notify_employee() alongside the
    existing in-app insert + email copy. Swallows all errors the same
    way notify_employee() does -- a broken push send should never affect
    the notification row that already got written.
    """
    if not employee_id:
        return

    try:
        rows = (
            supabase_admin.table("push_subscriptions")
            .select("endpoint, p256dh, auth")
            .eq("employee_id", employee_id)
            .execute()
        )
    except Exception as e:
        logger.error(f"Failed to look up push subscriptions for {employee_id}: {e}")
        return

    for row in rows.data or []:
        subscription = {
            "endpoint": row["endpoint"],
            "keys": {"p256dh": row["p256dh"], "auth": row["auth"]},
        }
        send_push(subscription, title=title, body=body, url=url)
