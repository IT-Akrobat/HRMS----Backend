"""
Generate a VAPID key pair for Web Push (see app/core/push.py).

Run once:
    python -m scripts.generate_vapid_keys

Copy the printed values into your .env as VAPID_PUBLIC_KEY and
VAPID_PRIVATE_KEY (see app/core/config.py). These identify this server
to browser push services (Chrome/Firefox's push endpoints) -- they are
not tied to any one user or device, so one pair covers the whole app.
Keep the private key secret; the public key is safe to expose to the
frontend (that's the whole point of GET /push-subscriptions/vapid-public-key).
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def main():
    vapid = Vapid02()
    vapid.generate_keys()

    # Browsers expect the VAPID public key as the raw 65-byte uncompressed
    # EC point (0x04 + x + y), base64url-encoded -- this is what gets
    # passed as `applicationServerKey` to pushManager.subscribe() on the
    # frontend. py_vapid's own helpers return DER/PEM instead, which the
    # browser Push API does not accept here, so this encodes it by hand.
    raw_point = vapid.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(raw_point).rstrip(b"=").decode("utf-8")
    private_key = vapid.private_pem().decode("utf-8")

    print("Add these to your .env:\n")
    print(f"VAPID_PUBLIC_KEY={public_key}")
    print("VAPID_PRIVATE_KEY=" + private_key.replace("\n", "\\n"))
    print(
        "\n(VAPID_PRIVATE_KEY is a PEM block -- if your .env loader chokes on "
        "the multi-line \\n form, paste it between triple-quotes instead, or "
        "store it as a secret file and point an env var at the path.)"
    )


if __name__ == "__main__":
    main()
