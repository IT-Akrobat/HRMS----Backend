import json

from py_vapid import Vapid01
from pywebpush import WebPushException, webpush

from app.core.config import VAPID_CLAIMS_EMAIL, VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY
from app.core.logger import logger

# ---------------------------------------------------------------------------
# webpush() accepts vapid_private_key as EITHER a Vapid01 instance OR a
# path to a PEM *file* -- if it's neither (e.g. our PEM string loaded from
# the env var), it silently falls through to py_vapid's Vapid.from_string(),
# which -- unlike from_file() -- does NOT check for a "-----BEGIN" header.
# It just strips newlines and base64url-decodes the whole string, headers
# included, producing garbage bytes and exactly the
# "Could not deserialize key data ... ASN.1 parsing error: invalid length"
# error this caused. Pre-parsing into a Vapid01 object here sidesteps that
# path entirely. Parsed once at import time since the key never changes at
# runtime; if VAPID_PRIVATE_KEY is missing/malformed, this stays None and
# push_configured() (below) reports push as unavailable rather than
# raising at import time.
# ---------------------------------------------------------------------------
_vapid: Vapid01 | None = None
if VAPID_PRIVATE_KEY:
    try:
        _vapid = Vapid01.from_pem(VAPID_PRIVATE_KEY.encode("utf8"))
    except Exception as e:
        logger.error(f"Could not parse VAPID_PRIVATE_KEY at startup: {e}")

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
    return bool(VAPID_PUBLIC_KEY and _vapid)


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
            vapid_private_key=_vapid,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
            ttl=60 * 60 * 24,  # push service holds it up to 24h if offline
        )
        return True

    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        body = getattr(e.response, "text", "") or str(e)

        # A subscription created under a since-rotated VAPID key pair can
        # never succeed again -- the push service (FCM/Mozilla autopush)
        # rejects it with 403 and this specific message forever, no
        # matter how many times we retry. Treat it the same as a
        # gone/expired subscription (404/410): prune it so the row stops
        # failing silently on every future notification and the user can
        # get a working subscription again next time they open the app.
        vapid_mismatch = status == 403 and "do not correspond" in body.lower()

        if status in (404, 410) or vapid_mismatch:
            reason = "VAPID key mismatch" if vapid_mismatch else f"gone ({status})"
            logger.info(f"Push subscription invalid ({reason}), pruning: {e}")
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
