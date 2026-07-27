import threading

from supabase import create_client
from supabase.client import ClientOptions

from app.core.config import SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY

# create_client() defaults to auto_refresh_token=True + persist_session=True.
# That's the right default for a browser/mobile app talking to Supabase
# directly, but wrong here: this client is shared/reused across many
# DIFFERENT users' requests (see _ThreadLocalSupabaseClient below). With
# auto-refresh on, whichever user's sign_in_with_password()/refresh_session()
# last ran on a given thread leaves its session cached on that client, which
# then silently rotates that user's refresh_token in the background on its
# own timer -- invalidating the refresh_token the frontend is still holding
# in sessionStorage. The next time the frontend calls POST /auth/refresh with
# its (now-stale) token, Supabase rejects it and the user gets logged out,
# sometimes within a minute of logging in. We do our own explicit refresh via
# /auth/refresh and verify bearer tokens per-request, so we don't want or
# need Supabase managing session state on this client at all.
_SERVER_SIDE_OPTIONS = ClientOptions(auto_refresh_token=False, persist_session=False)


class _ThreadLocalSupabaseClient:
    """
    supabase-py's client keeps a single shared httpx.Client for connection
    pooling. FastAPI runs our sync `def` route handlers in a worker thread
    pool, so when a page fires several requests at once (e.g. the employees
    page loading departments/designations/shifts/roles/employees together),
    multiple threads can hit that one shared httpx.Client at the same
    moment. httpcore's internal connection pool isn't safe against that —
    one thread can end up mutating it while another is iterating it, which
    surfaces as:

        RuntimeError: deque mutated during iteration

    A previous fix serialized every request behind a single lock, which
    removed the crash but made concurrent requests queue up one-by-one
    (visibly slow — each request waiting on the last). Instead, give each
    worker thread its own real Supabase client (built lazily the first time
    that thread needs one, then reused for that thread's lifetime). Threads
    then never share connection-pool state with each other, so the race is
    gone and requests stay concurrent. No call sites elsewhere need to
    change — they just keep doing `supabase_admin.table(...)...execute()`.
    """

    def __init__(self, url, key):
        self._url = url
        self._key = key
        self._local = threading.local()

    def _get(self):
        client = getattr(self._local, "client", None)
        if client is None:
            client = create_client(self._url, self._key, options=_SERVER_SIDE_OPTIONS)
            self._local.client = client
        return client

    def __getattr__(self, name):
        return getattr(self._get(), name)


supabase = _ThreadLocalSupabaseClient(SUPABASE_URL, SUPABASE_ANON_KEY)


supabase_admin = _ThreadLocalSupabaseClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
