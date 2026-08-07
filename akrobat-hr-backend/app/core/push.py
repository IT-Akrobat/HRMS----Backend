import json

from pywebpush import WebPushException, webpush

from app.core.config import VAPID_CLAIMS_EMAIL, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
from app.core.logger import logger

# ---------------------------------------------------------------------------
# Real browser/OS push notifications -- the piece that makes a notification
# pop up on a phone even when the HRMS tab/app isn't open, the same way
# WhatsApp's does. Used from app/notifications/services.py::notify_employee()
# alongside (not instead of) the existing in-app row + email copy.
#
# Deliberately not raise-on-failure, same reasoning as send_email(): a
# broken/expired push subscription, or VAPID keys not configured yet,
# should never fail the action that triggered the notification. Failures
# are logged and swallowed; the in-app notification (already written by
# notify_employee before this runs) is unaffected either way.
# ---------------------------------------------------------------------------


def push_configured() -> bool:
    return bool(VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY)


def send_push(subscription: dict, title: str, body: str, url: str = "/") -> bool:
    """
    subscription: {"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}
    -- the shape returned by the browser's PushSubscription.toJSON(),
    exactly as stored in push_subscriptions (see app/push_subscriptions).

    Returns False (never raises) on any failure, including a subscription
    that's gone stale/been revoked by the browser (410/404 from the push
    service) -- callers that want to clean up dead subscriptions should
    check push_subscriptions.services.prune_stale_subscription() instead
    of relying on this function's return value alone.
    """
    if not push_configured():
        logger.info(
            "VAPID keys not configured (VAPID_PUBLIC_KEY/VAPID_PRIVATE_KEY) "
            f"-- skipping push send: {title!r}"
        )
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": title, "body": body, "url": url}),
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
            ttl=60 * 60 * 24,  # push service holds it up to 24h if offline
        )
        return True

    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            # Subscription no longer valid (user revoked permission,
            # uninstalled, or the browser rotated it) -- not an error
            # worth logging loudly, just a stale row to clean up.
            logger.info(f"Push subscription gone ({status}), pruning: {e}")
            _prune(subscription.get("endpoint"))
        else:
            logger.error(f"Push send failed: {e}")
        return False

    except Exception as e:
        logger.error(f"Push send failed: {e}")
        return False


def _prune(endpoint: str | None):
    if not endpoint:
        return
    try:
        from app.push_subscriptions.services import delete_subscription_by_endpoint

        delete_subscription_by_endpoint(endpoint)
    except Exception as e:
        logger.error(f"Failed to prune stale push subscription: {e}")
