"""
Shared slowapi Limiter instance.

Lives in its own module (not app/main.py) so route files can import
`limiter` to decorate individual endpoints (e.g. @limiter.limit("5/minute")
on POST /auth/login) without creating a circular import with main.py,
which itself imports each router.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
