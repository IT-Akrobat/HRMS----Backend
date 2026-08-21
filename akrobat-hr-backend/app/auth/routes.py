from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    MeEnvelope,
    RefreshRequest,
)
from app.auth.services import change_password, get_me, login_user, refresh_user_session
from app.core.config import ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE
from app.core.cookies import clear_auth_cookies, issue_csrf_cookie, set_auth_cookies
from app.core.responses import success_response
from app.core.security import get_current_user
from app.core.limiter import limiter
from app.core.database import supabase_admin
from app.core.ws_tickets import issue_ticket

router = APIRouter(prefix="/auth", tags=["Authentication"])


# Rate-limited to 5 attempts/minute per IP so a script can't brute-force
# employee passwords. slowapi's Limiter needs the raw Request object as
# an argument on the route function itself (not just Depends) to read
# the caller's IP.
@router.post("/login")
@limiter.limit("5/minute")
def login(data: LoginRequest, request: Request, response: Response):

    try:

        session_response, mfa_required, password_expired = login_user(
            data.employee_code, data.password, request=request
        )

        # Tokens now go out as httpOnly cookies, never in the JSON body --
        # see app/core/cookies.py for why. The CSRF cookie is set here too,
        # but frontend+backend are deployed on separate domains (Vercel/
        # localhost + onrender.com) -- document.cookie on the frontend's
        # origin can never read a cookie set for the backend's domain, no
        # matter what SameSite/Secure say, since that's a per-domain
        # browser restriction. So the token is *also* returned in the body
        # here; the frontend caches it in memory and echoes it back as
        # X-CSRF-Token on every mutating request (see apiClient.js).
        set_auth_cookies(
            response,
            session_response.session.access_token,
            session_response.session.refresh_token,
        )
        csrf_token = issue_csrf_cookie(response)

        return {
            "user_id": session_response.user.id,
            "csrf_token": csrf_token,
            "mfa_required": mfa_required,
            "password_expired": password_expired,
            # Standalone-PWA fallback only (see apiClient.js's
            # getStandaloneRefreshToken/setStandaloneRefreshToken):
            # iOS's WKWebView, which backs "Add to Home Screen" apps,
            # doesn't reliably persist httpOnly cookies to disk before
            # the OS kills a backgrounded app process, so those clients
            # keep this in localStorage and send it back explicitly on
            # /auth/refresh instead of relying solely on the cookie.
            # Regular browser clients receive this too but never store
            # or use it -- the cookie remains the primary mechanism for
            # everyone.
            "refresh_token": session_response.session.refresh_token,
        }

    except HTTPException:
        raise

    except Exception:

        raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/refresh")
def refresh(data: RefreshRequest, request: Request, response: Response):
    """
    Exchanges a refresh_token for a new access_token — called by the
    frontend's apiClient whenever a request comes back 401 "Invalid or
    expired token.", instead of forcing a full re-login every time the
    ~1hr access token expires.

    Reads the refresh token from the httpOnly cookie by default (the
    normal browser flow); falls back to the request body only for a
    non-cookie client that explicitly passed one. See
    app/auth/schemas.py::RefreshRequest.
    """

    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE) or data.refresh_token

    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token provided.")

    session_response = refresh_user_session(refresh_token)

    # Supabase rotates the refresh token on every use -- always re-set
    # both cookies with the fresh pair, and reissue the CSRF cookie so
    # its lifetime keeps pace with the session instead of expiring first.
    set_auth_cookies(
        response,
        session_response.session.access_token,
        session_response.session.refresh_token,
    )
    csrf_token = issue_csrf_cookie(response)

    return {
        "user_id": session_response.user.id,
        "csrf_token": csrf_token,
        # See the matching comment in login() above -- standalone-PWA
        # fallback only. Also rotated here since Supabase rotates the
        # refresh token on every call; a client using the fallback MUST
        # overwrite its stored value with this one or the next refresh
        # will fail with a stale/reused token.
        "refresh_token": session_response.session.refresh_token,
    }


@router.get("/csrf")
def get_csrf_token(response: Response):
    """
    Re-issues the CSRF cookie and hands the token back in the body so the
    frontend can put it in memory (see apiClient.js).

    Why this route exists: /auth/login and /auth/refresh already return
    csrf_token, which covers a fresh session. But the frontend keeps that
    token in a plain JS variable, not localStorage (see cookies.py's
    reasoning on not keeping secrets in JS-readable storage) -- so a page
    reload wipes it, and document.cookie can't recover it either (see the
    comment in login() above). AuthContext calls this once on app load,
    alongside GET /auth/me, to have a valid token ready before the user's
    first click of the session. Safe/idempotent: GET isn't gated by
    CSRFMiddleware, and no auth is required to call it -- it just hands
    out a fresh double-submit token, same as login/refresh already do.
    """
    csrf_token = issue_csrf_cookie(response)
    return {"csrf_token": csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response):
    """
    Clears the auth cookies server-side (a client can't delete an
    httpOnly cookie itself) and best-effort revokes the token with
    Supabase so it can't be replayed elsewhere if it ever leaked before
    logout.
    """

    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if token:
        try:
            # The plain `supabase` client here is stateless (see
            # app/core/database.py -- persist_session=False), so it has no
            # session attached to sign out of. The admin API's sign_out
            # takes the JWT to revoke directly instead.
            supabase_admin.auth.admin.sign_out(token, "global")
        except Exception as e:
            print("LOGOUT SIGN_OUT WARNING:", e)

    clear_auth_cookies(response)
    return success_response(message="Logged out.")


@router.post("/change-password")
def change_password_route(
    data: ChangePasswordRequest,
    request: Request,
    user=Depends(get_current_user),
):
    """
    Self-service password change for the logged-in user. Verifies
    current_password by re-authenticating with Supabase, then rotates
    the password via the admin API. See app/auth/services.change_password.
    """

    result = change_password(
        user,
        data.current_password,
        data.new_password,
        request=request,
    )

    return success_response(message=result["message"])


@router.get("/ws-ticket")
def get_ws_ticket(user=Depends(get_current_user)):
    """
    Mints a short-lived, single-use ticket for opening a WebSocket
    connection (see app/core/ws_tickets.py and the /ws/dashboard,
    /ws/notifications handlers in app/main.py).

    Why this exists: the WS handshake can't rely on the access-token
    cookie alone when the frontend is proxied through a different site
    (e.g. a free Vercel rewrite proxy) -- normal fetch()/XHR calls go
    through that proxy and pick up the cookie fine, but a WebSocket
    upgrade can't be proxied the same way and connects straight to this
    API's own domain, where the browser may never have been allowed to
    store the cookie (iOS/Safari blocks third-party cookies). This route
    is called over the *proxied* connection -- so it's cookie-authed as
    normal -- and hands back a ticket the client appends as
    ?ticket=... on the direct WS URL instead.
    """
    ticket = issue_ticket(user.id)
    return {"ticket": ticket}


@router.get("/me", response_model=MeEnvelope)
def me(user=Depends(get_current_user)):
    """
    The frontend's single post-login call. Returns everything needed to
    decide the redirect target and render the sidebar — role, permissions,
    allowed modules, sidebar entries, and profile — so no role logic needs
    to live in the frontend. See app/auth/services.get_me.
    """

    data = get_me(user)

    return success_response(message="User profile fetched successfully.", data=data)
