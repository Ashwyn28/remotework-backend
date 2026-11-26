import base64
import json
import unittest

from jobapi import sessions
from jobapi.app import App, Config, Request, parse_cookies
from jobapi.lambda_handler import handler
from jobapi.store import DynamoStore, MemoryStore

ORIGIN = "https://jobs.example.com"
CLAIMS = {
    "sub": "1234567890",
    "email": "seeker@example.com",
    "email_verified": True,
    "given_name": "Sam",
}
PREFERENCES = {
    "industries": ["fintech", "ai"],
    "places": ["london"],
    "workTypes": ["engineering"],
    "seniorities": ["senior"],
    "stages": [],
    "minSalary": 80,
}


class Browser:
    """Keeps cookies between requests and sends the CSRF header the way the site does."""

    def __init__(self, app: App, origin: str = ORIGIN, origin_secret: str = ""):
        self.app = app
        self.origin = origin
        self.origin_secret = origin_secret
        self.cookies: dict[str, str] = {}

    def send(self, method, path, body=None, csrf=True, extra_headers=None):
        headers = {"origin": self.origin} if method != "GET" else {}
        if csrf and method != "GET":
            headers["x-csrftoken"] = self.cookies.get("csrftoken", "")
        if self.origin_secret:
            headers["x-origin-verify"] = self.origin_secret
        headers.update(extra_headers or {})
        raw = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else (body or b"")
        response = self.app.handle(Request(method, path, headers, dict(self.cookies), raw))
        for cookie in response.cookies:
            name, _, rest = cookie.partition("=")
            value = rest.split(";", 1)[0]
            if "Max-Age=0" in cookie:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response


def make_app(claims=CLAIMS, origin_secret="", store=None):
    def verify(credential, client_id):
        assert client_id == "client-id.apps.googleusercontent.com"
        if credential != "good-token":
            raise ValueError("bad signature")
        return claims

    config = Config("client-id.apps.googleusercontent.com", "s" * 40, ORIGIN, True, origin_secret)
    return App(config, store or MemoryStore(), verify)


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.app = make_app()
        self.browser = Browser(self.app)
        self.browser.send("GET", "/api/auth/config/")

    def sign_in(self, browser=None):
        return (browser or self.browser).send("POST", "/api/auth/google/", {"credential": "good-token"})

    def test_config_gives_client_id_and_csrf_cookie(self):
        response = Browser(self.app).send("GET", "/api/auth/config/")
        self.assertEqual(response.body["google_client_id"], "client-id.apps.googleusercontent.com")
        (cookie,) = response.cookies
        self.assertTrue(cookie.startswith("csrftoken="))
        self.assertNotIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)

    def test_signed_out_visitor(self):
        self.assertEqual(self.browser.send("GET", "/api/me/").body, {"authenticated": False})
        self.assertEqual(self.browser.send("PUT", "/api/me/", {"preferences": PREFERENCES}).status, 401)

    def test_sign_in_sets_a_locked_down_session_cookie(self):
        response = self.sign_in()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.body["user"], {"name": "Sam", "email": "seeker@example.com"})
        session = next(c for c in response.cookies if c.startswith("session="))
        for part in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/api"):
            self.assertIn(part, session)
        self.assertTrue(self.browser.send("GET", "/api/me/").body["authenticated"])

    def test_sign_in_rotates_the_csrf_token(self):
        before = self.browser.cookies["csrftoken"]
        self.sign_in()
        self.assertNotEqual(self.browser.cookies["csrftoken"], before)

    def test_signing_in_again_keeps_data_and_follows_email_changes(self):
        self.sign_in()
        self.browser.send("PUT", "/api/me/", {"preferences": PREFERENCES})
        self.app.verify_google = lambda c, cid: {**CLAIMS, "email": "new@example.com"}
        self.sign_in()

        me = self.browser.send("GET", "/api/me/").body
        self.assertEqual(me["user"]["email"], "new@example.com")
        self.assertEqual(me["preferences"], PREFERENCES)
        self.assertEqual(len(self.app.store.users), 1)

    def test_refuses_writes_without_matching_csrf_token(self):
        self.assertEqual(self.browser.send("POST", "/api/auth/google/", {"credential": "good-token"}, csrf=False).status, 403)
        wrong = self.browser.send(
            "POST", "/api/auth/google/", {"credential": "good-token"}, csrf=False, extra_headers={"x-csrftoken": "guess"}
        )
        self.assertEqual(wrong.status, 403)
        self.assertEqual(self.app.store.users, {})

    def test_refuses_writes_from_another_site(self):
        evil = Browser(self.app, origin="https://evil.example")
        evil.cookies = dict(self.browser.cookies)
        self.assertEqual(evil.send("POST", "/api/auth/google/", {"credential": "good-token"}).status, 403)

    def test_invalid_or_unverified_google_tokens(self):
        self.assertEqual(self.browser.send("POST", "/api/auth/google/", {"credential": "forged"}).status, 401)
        self.app.verify_google = lambda c, cid: {**CLAIMS, "email_verified": False}
        self.assertEqual(self.sign_in().status, 401)
        self.assertEqual(self.app.store.users, {})

    def test_malformed_sign_in_requests(self):
        self.assertEqual(self.browser.send("POST", "/api/auth/google/", {}).status, 400)
        self.assertEqual(self.browser.send("POST", "/api/auth/google/", b"not json").status, 400)
        self.assertEqual(self.browser.send("POST", "/api/auth/google/", ["list"]).status, 400)

    def test_saves_and_returns_answers_and_saved_roles(self):
        self.sign_in()
        tracked = {"6d05418308a2bdbe": {"status": "saved", "at": 1763200000000}}

        self.assertEqual(self.browser.send("PUT", "/api/me/", {"preferences": PREFERENCES, "tracked": tracked}).status, 200)

        me = self.browser.send("GET", "/api/me/").body
        self.assertEqual((me["preferences"], me["tracked"]), (PREFERENCES, tracked))

    def test_saving_one_part_leaves_the_other(self):
        self.sign_in()
        self.browser.send("PUT", "/api/me/", {"preferences": PREFERENCES})
        self.browser.send("PUT", "/api/me/", {"tracked": {"abc": {"status": "applied", "at": 1}}})
        self.assertEqual(self.browser.send("GET", "/api/me/").body["preferences"], PREFERENCES)

    def test_rejects_bad_data(self):
        self.sign_in()
        bad = [
            {"preferences": {**PREFERENCES, "places": ["mars"]}},
            {"preferences": {**PREFERENCES, "industries": ["<script>"]}},
            {"preferences": {**PREFERENCES, "minSalary": "lots"}},
            {"tracked": {"NOT-HEX": {"status": "saved", "at": 1}}},
            {"tracked": {"1": {"status": "hired", "at": 1}}},
            ["not", "an", "object"],
            b"x" * (300 * 1024),
        ]
        for body in bad:
            with self.subTest(body=str(body)[:50]):
                self.assertEqual(self.browser.send("PUT", "/api/me/", body).status, 400)

    def test_sign_out_clears_the_session(self):
        self.sign_in()
        self.browser.send("POST", "/api/auth/sign-out/")
        self.assertEqual(self.browser.send("GET", "/api/me/").body, {"authenticated": False})

    def test_delete_account_removes_everything_and_old_cookies_stop_working(self):
        self.sign_in()
        stolen = dict(self.browser.cookies)
        self.assertEqual(self.browser.send("DELETE", "/api/me/").status, 200)

        self.assertEqual(self.app.store.users, {})
        thief = Browser(self.app)
        thief.cookies = stolen
        self.assertEqual(thief.send("GET", "/api/me/").body, {"authenticated": False})

    def test_tampered_or_expired_sessions_are_ignored(self):
        self.sign_in()
        token = self.browser.cookies["session"]
        payload, signature = token.split(".")
        forged = base64.urlsafe_b64encode(json.dumps({"sub": "someone-else", "v": 1, "iat": 9e9}).encode()).decode()
        self.assertIsNone(sessions.read("s" * 40, f"{forged.rstrip('=')}.{signature}"))
        self.assertIsNone(sessions.read("s" * 40, token, now=9e12))
        self.assertIsNone(sessions.read("other-secret", token))
        self.assertIsNotNone(sessions.read("s" * 40, token))

    def test_one_seeker_cannot_see_another(self):
        self.sign_in()
        self.browser.send("PUT", "/api/me/", {"preferences": PREFERENCES})
        other = Browser(self.app)
        other.send("GET", "/api/auth/config/")
        self.app.verify_google = lambda c, cid: {**CLAIMS, "sub": "999", "email": "b@example.com"}
        self.sign_in(other)

        self.assertEqual(other.send("GET", "/api/me/").body["preferences"], {})

    def test_unknown_paths_and_methods(self):
        self.assertEqual(self.browser.send("GET", "/api/nope/").status, 404)
        self.assertEqual(self.browser.send("GET", "/api/auth/google/").status, 405)


class OriginSecretTests(unittest.TestCase):
    def test_requests_that_bypass_cloudfront_are_refused(self):
        app = make_app(origin_secret="from-cloudfront")
        self.assertEqual(Browser(app).send("GET", "/api/me/").status, 403)
        self.assertEqual(Browser(app, origin_secret="wrong").send("GET", "/api/me/").status, 403)
        self.assertEqual(Browser(app, origin_secret="from-cloudfront").send("GET", "/api/me/").status, 200)


class LambdaAdapterTests(unittest.TestCase):
    def test_translates_function_url_events(self):
        app = make_app()
        event = {
            "rawPath": "/api/auth/config/",
            "requestContext": {"http": {"method": "GET", "path": "/api/auth/config/"}},
            "headers": {"Accept": "application/json"},
            "cookies": [],
            "isBase64Encoded": False,
        }
        result = handler(event, None, app=app)
        self.assertEqual(result["statusCode"], 200)
        self.assertEqual(result["headers"]["Cache-Control"], "no-store")
        self.assertTrue(result["cookies"][0].startswith("csrftoken="))
        token = result["cookies"][0].split(";")[0].split("=", 1)[1]

        sign_in = {
            "rawPath": "/api/auth/google/",
            "requestContext": {"http": {"method": "POST", "path": "/api/auth/google/"}},
            "headers": {"Origin": ORIGIN, "X-CSRFToken": token, "Content-Type": "application/json"},
            "cookies": [f"csrftoken={token}"],
            "body": base64.b64encode(json.dumps({"credential": "good-token"}).encode()).decode(),
            "isBase64Encoded": True,
        }
        result = handler(sign_in, None, app=app)
        self.assertEqual(result["statusCode"], 200, result["body"])
        self.assertTrue(any(c.startswith("session=") for c in result["cookies"]))

    def test_parse_cookies(self):
        self.assertEqual(parse_cookies(["a=1; b=2", "c=3"]), {"a": "1", "b": "2", "c": "3"})


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key, ConsistentRead):  # noqa: N803 - boto3 names
        item = self.items.get(Key["sub"])
        return {"Item": item} if item else {}

    def put_item(self, Item):  # noqa: N803
        self.items[Item["sub"]] = Item

    def delete_item(self, Key):  # noqa: N803
        self.items.pop(Key["sub"], None)


class DynamoStoreTests(unittest.TestCase):
    def test_round_trips_an_account(self):
        table = FakeTable()
        store = DynamoStore("users", table=table)
        user = {"sub": "1", "email": "a@b.c", "name": "A", "preferences": PREFERENCES,
                "tracked": {"ab": {"status": "saved", "at": 5}}, "session_version": 2,
                "created_at": "x", "updated_at": "y"}
        store.put(user)

        self.assertIsInstance(table.items["1"]["preferences"], str)  # stored as JSON text
        self.assertEqual(store.get("1"), user)
        store.delete("1")
        self.assertIsNone(store.get("1"))


if __name__ == "__main__":
    unittest.main()
