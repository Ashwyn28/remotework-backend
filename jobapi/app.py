"""The accounts API as plain request handling: method, path, headers, cookies and body in;
status, headers, cookies and body out. Adapters for Lambda and the local server sit on top.

Endpoints (all under /api):
    GET    /api/auth/config/   Google client id; sets the CSRF cookie
    POST   /api/auth/google/   sign in with a Google ID token
    POST   /api/auth/sign-out/
    GET    /api/me/            who is signed in, with their answers and saved roles
    PUT    /api/me/            save answers and/or saved roles
    DELETE /api/me/            delete the account
"""
from __future__ import annotations

import hmac
import json
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from . import sessions, validation
from .store import UserStore

log = logging.getLogger(__name__)

MAX_BODY = 256 * 1024
SESSION_COOKIE = "session"
CSRF_COOKIE = "csrftoken"
CSRF_HEADER = "x-csrftoken"
ORIGIN_HEADER = "x-origin-verify"
UNSAFE = {"POST", "PUT", "DELETE", "PATCH"}


@dataclass(frozen=True)
class Config:
    google_client_id: str
    session_secret: str
    site_origin: str  # e.g. "https://jobs.orbbits.io"; writes from any other origin are refused
    secure_cookies: bool = True
    # CloudFront adds this header; requests that arrive any other way are refused. Empty locally.
    origin_secret: str = ""


@dataclass
class Request:
    method: str
    path: str
    headers: dict[str, str]  # lower-case names
    cookies: dict[str, str]
    body: bytes = b""


@dataclass
class Response:
    status: int
    body: dict
    cookies: list[str] = field(default_factory=list)

    def json(self) -> str:
        return json.dumps(self.body)


# verifies a Google ID token for our client id and returns its claims, or raises ValueError
GoogleVerifier = Callable[[str, str], dict]


def verify_with_google(credential: str, client_id: str) -> dict:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)


class App:
    def __init__(self, config: Config, store: UserStore, verify_google: GoogleVerifier = verify_with_google):
        self.config = config
        self.store = store
        self.verify_google = verify_google

    # -- cookies ---------------------------------------------------------------------------

    def _cookie(self, name: str, value: str, max_age: int, http_only: bool, path: str = "/") -> str:
        parts = [f"{name}={value}", f"Path={path}", f"Max-Age={max_age}", "SameSite=Lax"]
        if http_only:
            parts.append("HttpOnly")
        if self.config.secure_cookies:
            parts.append("Secure")
        return "; ".join(parts)

    def _session_cookie(self, user: dict) -> str:
        token = sessions.issue(self.config.session_secret, user["sub"], user["session_version"])
        # only ever sent to the API, never with page or file requests
        return self._cookie(SESSION_COOKIE, token, sessions.MAX_AGE, http_only=True, path="/api")

    def _clear_session(self) -> str:
        return self._cookie(SESSION_COOKIE, "", 0, http_only=True, path="/api")

    def _new_csrf(self) -> str:
        # readable by the page, which copies it into a header; another site can do neither
        return self._cookie(CSRF_COOKIE, secrets.token_urlsafe(32), 365 * 24 * 3600, http_only=False)

    # -- checks ----------------------------------------------------------------------------

    def _from_cloudfront(self, request: Request) -> bool:
        if not self.config.origin_secret:
            return True
        return hmac.compare_digest(request.headers.get(ORIGIN_HEADER, ""), self.config.origin_secret)

    def _csrf_ok(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin and origin != self.config.site_origin:
            return False
        cookie = request.cookies.get(CSRF_COOKIE, "")
        header = request.headers.get(CSRF_HEADER, "")
        return bool(cookie) and hmac.compare_digest(cookie, header)

    def _current_user(self, request: Request) -> dict | None:
        found = sessions.read(self.config.session_secret, request.cookies.get(SESSION_COOKIE))
        if not found:
            return None
        sub, version = found
        user = self.store.get(sub)
        if not user or user.get("session_version", 1) != version:
            return None
        return user

    @staticmethod
    def _me(user: dict) -> dict:
        return {
            "authenticated": True,
            "user": {"name": user.get("name", ""), "email": user.get("email", "")},
            "preferences": user.get("preferences") or {},
            "tracked": user.get("tracked") or {},
        }

    @staticmethod
    def _body(request: Request):
        if len(request.body) > MAX_BODY:
            raise validation.Invalid("request too large")
        try:
            return json.loads(request.body or b"{}")
        except ValueError as error:
            raise validation.Invalid("request body must be JSON") from error

    # -- routing ---------------------------------------------------------------------------

    def handle(self, request: Request) -> Response:
        if not self._from_cloudfront(request):
            return Response(403, {"error": "Forbidden"})
        if request.method in UNSAFE and not self._csrf_ok(request):
            return Response(403, {"error": "Refresh the page and try again."})
        routes = {
            ("GET", "/api/auth/config/"): self.config_route,
            ("POST", "/api/auth/google/"): self.google_sign_in,
            ("POST", "/api/auth/sign-out/"): self.sign_out,
            ("GET", "/api/me/"): self.me,
            ("PUT", "/api/me/"): self.save,
            ("DELETE", "/api/me/"): self.delete,
        }
        route = routes.get((request.method, request.path))
        if route:
            return route(request)
        if any(path == request.path for _, path in routes):
            return Response(405, {"error": "Method not allowed"})
        return Response(404, {"error": "Not found"})

    def config_route(self, request: Request) -> Response:
        response = Response(200, {"google_client_id": self.config.google_client_id})
        if not request.cookies.get(CSRF_COOKIE):
            response.cookies.append(self._new_csrf())
        return response

    def google_sign_in(self, request: Request) -> Response:
        try:
            body = self._body(request)
        except validation.Invalid as error:
            return Response(400, {"error": str(error)})
        credential = body.get("credential") if isinstance(body, dict) else None
        if not isinstance(credential, str) or not credential or len(credential) > 8192:
            return Response(400, {"error": "Missing Google credential"})
        try:
            claims = self.verify_google(credential, self.config.google_client_id)
            if not claims.get("email_verified"):
                raise ValueError("Google has not verified this email address")
        except Exception as error:  # noqa: BLE001 - any verification failure means "not signed in"
            log.info("Rejected Google sign-in: %s", error)
            return Response(401, {"error": "Google sign-in could not be verified. Please try again."})

        now = datetime.now(timezone.utc).isoformat()
        user = self.store.get(claims["sub"]) or {
            "sub": claims["sub"],
            "preferences": {},
            "tracked": {},
            "session_version": 1,
            "created_at": now,
        }
        user["email"] = claims.get("email", "")
        user["name"] = (claims.get("given_name") or claims.get("name") or "")[:150]
        user["updated_at"] = now
        self.store.put(user)
        # a fresh CSRF token too, so one planted before sign-in is useless afterwards
        return Response(200, self._me(user), [self._session_cookie(user), self._new_csrf()])

    def sign_out(self, request: Request) -> Response:
        return Response(200, {"authenticated": False}, [self._clear_session()])

    def me(self, request: Request) -> Response:
        user = self._current_user(request)
        response = Response(200, self._me(user) if user else {"authenticated": False})
        if not request.cookies.get(CSRF_COOKIE):
            response.cookies.append(self._new_csrf())
        if not user and request.cookies.get(SESSION_COOKIE):
            response.cookies.append(self._clear_session())  # expired or revoked: tidy it away
        return response

    def save(self, request: Request) -> Response:
        user = self._current_user(request)
        if not user:
            return Response(401, {"error": "Sign in first"})
        try:
            body = self._body(request)
            if not isinstance(body, dict):
                raise validation.Invalid("expected an object")
            if "preferences" in body:
                user["preferences"] = validation.preferences(body["preferences"])
            if "tracked" in body:
                user["tracked"] = validation.tracked(body["tracked"])
        except validation.Invalid as error:
            return Response(400, {"error": str(error)})
        user["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.store.put(user)
        return Response(200, self._me(user))

    def delete(self, request: Request) -> Response:
        user = self._current_user(request)
        if not user:
            return Response(401, {"error": "Sign in first"})
        self.store.delete(user["sub"])
        return Response(200, {"authenticated": False}, [self._clear_session()])


def parse_cookies(values: list[str]) -> dict[str, str]:
    cookies = {}
    for value in values:
        for part in value.split(";"):
            name, sep, content = part.strip().partition("=")
            if sep and name and name not in cookies:
                cookies[name] = content
    return cookies
