import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from accounts.models import SeekerProfile

CLAIMS = {
    "sub": "1234567890",
    "email": "seeker@example.com",
    "email_verified": True,
    "given_name": "Sam",
    "name": "Sam Seeker",
}
PREFERENCES = {
    "industries": ["fintech", "ai"],
    "places": ["london"],
    "workTypes": ["engineering"],
    "seniorities": ["senior"],
    "stages": [],
    "minSalary": 80,
}


class AccountTests(TestCase):
    def setUp(self):
        # a real browser: every write must carry the CSRF token from the cookie
        self.client = Client(enforce_csrf_checks=True)

    def csrf(self) -> str:
        self.client.get("/api/auth/config/")
        return self.client.cookies["csrftoken"].value

    def call(self, method: str, path: str, body=None, csrf: bool = True):
        headers = {"HTTP_X_CSRFTOKEN": self.csrf()} if csrf else {}
        return getattr(self.client, method)(
            path, data=json.dumps(body) if body is not None else None, content_type="application/json", **headers
        )

    def sign_in(self, claims=CLAIMS):
        with mock.patch("accounts.views.verify_google_credential", return_value=claims):
            return self.call("post", "/api/auth/google/", {"credential": "google-id-token"})

    def test_config_gives_client_id_and_csrf_cookie(self):
        response = self.client.get("/api/auth/config/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["google_client_id"].endswith(".apps.googleusercontent.com"))
        self.assertIn("csrftoken", response.cookies)

    def test_checking_who_is_signed_in_sets_the_csrf_cookie(self):
        # a visitor who arrives already signed in never loads the sign-in page
        self.assertIn("csrftoken", self.client.get("/api/me/").cookies)

    def test_signed_out_visitor(self):
        self.assertEqual(self.client.get("/api/me/").json(), {"authenticated": False})
        self.assertEqual(self.call("put", "/api/me/", {"preferences": PREFERENCES}).status_code, 401)

    def test_sign_in_creates_an_account_and_a_session(self):
        response = self.sign_in()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"], {"name": "Sam", "email": "seeker@example.com"})
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertEqual(response.cookies["sessionid"]["samesite"], "Lax")
        user = get_user_model().objects.get()
        self.assertFalse(user.has_usable_password())
        self.assertEqual(self.client.get("/api/me/").json()["user"]["email"], "seeker@example.com")

    def test_signing_in_again_reuses_the_account_and_follows_email_changes(self):
        self.sign_in()
        self.call("post", "/api/auth/sign-out/")
        self.sign_in({**CLAIMS, "email": "new@example.com"})

        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(get_user_model().objects.get().email, "new@example.com")

    def test_sign_in_is_refused_without_csrf_token(self):
        with mock.patch("accounts.views.verify_google_credential", return_value=CLAIMS):
            response = self.call("post", "/api/auth/google/", {"credential": "x"}, csrf=False)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(get_user_model().objects.exists())

    def test_invalid_google_token_is_refused(self):
        with mock.patch("accounts.views.verify_google_credential", side_effect=ValueError("bad signature")):
            response = self.call("post", "/api/auth/google/", {"credential": "forged"})

        self.assertEqual(response.status_code, 401)
        self.assertFalse(get_user_model().objects.exists())

    def test_unverified_email_is_refused(self):
        from accounts import views

        with mock.patch.object(views.id_token, "verify_oauth2_token", return_value={**CLAIMS, "email_verified": False}):
            response = self.call("post", "/api/auth/google/", {"credential": "token"})

        self.assertEqual(response.status_code, 401)

    def test_google_token_is_checked_against_our_client_id(self):
        from accounts import views

        with mock.patch.object(views.id_token, "verify_oauth2_token", return_value=CLAIMS) as verify:
            self.call("post", "/api/auth/google/", {"credential": "token"})

        self.assertEqual(verify.call_args.args[2], views.settings.GOOGLE_CLIENT_ID)

    def test_missing_or_malformed_credential(self):
        self.assertEqual(self.call("post", "/api/auth/google/", {}).status_code, 400)
        response = self.client.post(
            "/api/auth/google/", data="not json", content_type="application/json", HTTP_X_CSRFTOKEN=self.csrf()
        )
        self.assertEqual(response.status_code, 400)

    def test_saves_and_returns_answers_and_saved_roles(self):
        self.sign_in()
        tracked = {"42": {"status": "saved", "at": 1763200000000}}

        response = self.call("put", "/api/me/", {"preferences": PREFERENCES, "tracked": tracked})

        self.assertEqual(response.status_code, 200)
        me = self.client.get("/api/me/").json()
        self.assertEqual(me["preferences"], PREFERENCES)
        self.assertEqual(me["tracked"], tracked)

    def test_saving_one_part_leaves_the_other(self):
        self.sign_in()
        self.call("put", "/api/me/", {"preferences": PREFERENCES})
        self.call("put", "/api/me/", {"tracked": {"7": {"status": "applied", "at": 1}}})

        self.assertEqual(self.client.get("/api/me/").json()["preferences"], PREFERENCES)

    def test_rejects_bad_data(self):
        self.sign_in()
        bad = [
            {"preferences": {**PREFERENCES, "places": ["mars"]}},
            {"preferences": {**PREFERENCES, "industries": ["<script>"]}},
            {"preferences": {**PREFERENCES, "minSalary": "lots"}},
            {"preferences": {**PREFERENCES, "industries": ["x"] * 100}},
            {"tracked": {"NOT-HEX": {"status": "saved", "at": 1}}},
            {"tracked": {"1": {"status": "hired", "at": 1}}},
            {"tracked": {"1": {"status": "saved", "at": -5}}},
            ["not", "an", "object"],
        ]
        for body in bad:
            with self.subTest(body=str(body)[:60]):
                self.assertEqual(self.call("put", "/api/me/", body).status_code, 400)
        self.assertEqual(SeekerProfile.objects.get().preferences, {})

    def test_unknown_preference_fields_are_dropped(self):
        self.sign_in()
        self.call("put", "/api/me/", {"preferences": {**PREFERENCES, "isAdmin": True}})

        self.assertNotIn("isAdmin", self.client.get("/api/me/").json()["preferences"])

    def test_writes_need_csrf_token_even_when_signed_in(self):
        self.sign_in()

        self.assertEqual(self.call("put", "/api/me/", {"preferences": PREFERENCES}, csrf=False).status_code, 403)

    def test_sign_out_ends_the_session(self):
        self.sign_in()
        self.call("post", "/api/auth/sign-out/")

        self.assertEqual(self.client.get("/api/me/").json(), {"authenticated": False})

    def test_delete_account_removes_everything(self):
        self.sign_in()
        self.call("put", "/api/me/", {"preferences": PREFERENCES})

        response = self.call("delete", "/api/me/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.exists())
        self.assertFalse(SeekerProfile.objects.exists())
        self.assertEqual(self.client.get("/api/me/").json(), {"authenticated": False})

    def test_one_seeker_cannot_see_another(self):
        self.sign_in()
        self.call("put", "/api/me/", {"preferences": PREFERENCES})
        other = Client(enforce_csrf_checks=True)
        other.get("/api/auth/config/")
        with mock.patch("accounts.views.verify_google_credential", return_value={**CLAIMS, "sub": "999", "email": "b@example.com"}):
            other.post(
                "/api/auth/google/",
                data=json.dumps({"credential": "t"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=other.cookies["csrftoken"].value,
            )

        self.assertEqual(other.get("/api/me/").json()["preferences"], {})
        self.assertEqual(other.get("/api/me/").json()["user"]["email"], "b@example.com")
