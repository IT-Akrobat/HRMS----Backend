from pydantic import BaseModel


# Matches the shape of PushSubscription.toJSON() from the browser Push
# API exactly, so the frontend can forward it with no reshaping:
#   { endpoint, keys: { p256dh, auth } }
class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribePushRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    user_agent: str | None = None


class UnsubscribePushRequest(BaseModel):
    endpoint: str
