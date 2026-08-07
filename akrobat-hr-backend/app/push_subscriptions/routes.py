from fastapi import APIRouter, Depends

from app.core.config import VAPID_PUBLIC_KEY
from app.core.responses import success_response
from app.core.security import get_current_user
from app.push_subscriptions.schemas import SubscribePushRequest, UnsubscribePushRequest
from app.push_subscriptions.services import subscribe, unsubscribe

router = APIRouter(prefix="/push-subscriptions", tags=["Push Subscriptions"])


# =========================
# PUBLIC KEY (no auth -- the frontend needs this before it even knows
# who's logged in, to call pushManager.subscribe())
# =========================


@router.get("/vapid-public-key")
def vapid_public_key():
    return success_response(
        message="Vapid public key fetched.",
        data={"public_key": VAPID_PUBLIC_KEY},
    )


# =========================
# SUBSCRIBE THIS DEVICE
# =========================


@router.post("/subscribe")
def subscribe_device(data: SubscribePushRequest, user=Depends(get_current_user)):
    return subscribe(
        user.id,
        endpoint=data.endpoint,
        p256dh=data.keys.p256dh,
        auth=data.keys.auth,
        user_agent=data.user_agent,
    )


# =========================
# UNSUBSCRIBE THIS DEVICE
# =========================


@router.post("/unsubscribe")
def unsubscribe_device(data: UnsubscribePushRequest, user=Depends(get_current_user)):
    return unsubscribe(user.id, endpoint=data.endpoint)
