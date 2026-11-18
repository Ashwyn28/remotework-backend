"""Sign in with Google, and keep a signed-in job seeker's answers and saved roles.

These are plain Django views on purpose: Django's CSRF middleware protects every POST, PUT
and DELETE, including sign-in, and the session lives in an HttpOnly cookie that page
scripts cannot read.
"""
import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from google.auth.exceptions import GoogleAuthError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from . import validation
from .models import SeekerProfile

log = logging.getLogger(__name__)
MAX_BODY = 256 * 1024


def _json_body(request):
    if len(request.body) > MAX_BODY:
        raise validation.Invalid("request too large")
    try:
        return json.loads(request.body or b"{}")
    except ValueError as error:
        raise validation.Invalid("request body must be JSON") from error


def _me(user):
    profile = getattr(user, "seeker", None)
    return {
        "authenticated": True,
        "user": {"name": user.first_name, "email": user.email},
        "preferences": profile.preferences if profile else {},
        "tracked": profile.tracked if profile else {},
    }


def verify_google_credential(credential: str) -> dict:
    """The verified claims from a Google ID token, or raise ValueError."""
    claims = id_token.verify_oauth2_token(credential, google_requests.Request(), settings.GOOGLE_CLIENT_ID)
    if not claims.get("email_verified"):
        raise ValueError("Google has not verified this email address")
    return claims


@require_GET
@ensure_csrf_cookie
def config(request):
    """Public sign-in settings. Also sets the CSRF cookie the browser sends back on writes."""
    return JsonResponse({"google_client_id": settings.GOOGLE_CLIENT_ID})


@require_POST
def google_sign_in(request):
    try:
        credential = _json_body(request).get("credential")
    except validation.Invalid as error:
        return JsonResponse({"error": str(error)}, status=400)
    if not isinstance(credential, str) or not credential or len(credential) > 8192:
        return JsonResponse({"error": "Missing Google credential"}, status=400)
    try:
        claims = verify_google_credential(credential)
    except (ValueError, GoogleAuthError) as error:
        log.info("Rejected Google sign-in: %s", error)
        return JsonResponse({"error": "Google sign-in could not be verified. Please try again."}, status=401)

    User = get_user_model()
    with transaction.atomic():
        profile = SeekerProfile.objects.select_related("user").filter(google_sub=claims["sub"]).first()
        if profile:
            user = profile.user
        else:
            user = User.objects.create_user(username=f"google_{claims['sub']}"[:150])
            user.set_unusable_password()  # Google is the only way in
            profile = SeekerProfile.objects.create(user=user, google_sub=claims["sub"])
        user.email = claims.get("email", "")
        user.first_name = (claims.get("given_name") or claims.get("name") or "")[:150]
        user.save(update_fields=["email", "first_name", "password"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return JsonResponse(_me(user))


@require_POST
def sign_out(request):
    logout(request)
    return JsonResponse({"authenticated": False})


@require_http_methods(["GET", "PUT", "DELETE"])
@ensure_csrf_cookie  # every visit checks who is signed in, so the browser always holds a CSRF token
def me(request):
    if not request.user.is_authenticated:
        if request.method == "GET":
            return JsonResponse({"authenticated": False})
        return JsonResponse({"error": "Sign in first"}, status=401)
    profile, _ = SeekerProfile.objects.get_or_create(
        user=request.user, defaults={"google_sub": f"user:{request.user.pk}"}
    )

    if request.method == "PUT":
        try:
            body = _json_body(request)
            if not isinstance(body, dict):
                raise validation.Invalid("expected an object")
            changed = []
            if "preferences" in body:
                profile.preferences = validation.preferences(body["preferences"])
                changed.append("preferences")
            if "tracked" in body:
                profile.tracked = validation.tracked(body["tracked"])
                changed.append("tracked")
        except validation.Invalid as error:
            return JsonResponse({"error": str(error)}, status=400)
        if changed:
            profile.save(update_fields=[*changed, "updated_at"])

    if request.method == "DELETE":
        user = request.user
        logout(request)
        user.delete()  # removes the profile too
        return JsonResponse({"authenticated": False})

    return JsonResponse(_me(request.user))
