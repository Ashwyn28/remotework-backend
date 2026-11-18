"""Run the site's backend locally, laid out as CloudFront serves it in production:

    /api/...      the accounts API (in memory: accounts vanish when the server stops)
    /data/...     files built by `python -m jobfeed sync`
    /static/...   company logos from the same folder

    python -m jobapi.devserver --data .local/site-data --port 8787

Google sign-in is verified for real, so the Google button works if this origin is allowed in
the Google Cloud console. Never run this on a public network: it is for development only.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .app import App, Config, Request, parse_cookies, verify_with_google
from .store import MemoryStore

DEFAULT_CLIENT_ID = "601837645469-i46geu02ca7rthamniuehgkp5ithjbl9.apps.googleusercontent.com"


def make_handler(app: App, data_root: Path):
    data_root = data_root.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _api(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            request = Request(
                method=method,
                path=self.path.split("?", 1)[0],
                headers={name.lower(): value for name, value in self.headers.items()},
                cookies=parse_cookies(self.headers.get_all("Cookie") or []),
                body=self.rfile.read(length) if length else b"",
            )
            response = app.handle(request)
            body = response.json().encode()
            self.send_response(response.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            for cookie in response.cookies:
                self.send_header("Set-Cookie", cookie)
            self.end_headers()
            self.wfile.write(body)

        def _file(self) -> None:
            path = (data_root / self.path.split("?", 1)[0].lstrip("/")).resolve()
            if data_root not in path.parents or not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/"):
                self._api("GET")
            elif self.path.startswith(("/data/", "/static/")):
                self._file()
            else:
                self.send_error(404)

        def do_POST(self):  # noqa: N802
            self._api("POST")

        def do_PUT(self):  # noqa: N802
            self._api("PUT")

        def do_DELETE(self):  # noqa: N802
            self._api("DELETE")

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=".local/site-data")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--site-origin", default="http://localhost:3001")
    parser.add_argument(
        "--accept-test-credentials",
        action="store_true",
        help='also accept "test:<id>:<email>" as a Google credential, for automated browser tests',
    )
    args = parser.parse_args()

    def verify(credential: str, client_id: str) -> dict:
        if args.accept_test_credentials and credential.startswith("test:"):
            _, sub, email = credential.split(":", 2)
            return {"sub": f"test-{sub}", "email": email, "email_verified": True, "given_name": "Test"}
        return verify_with_google(credential, client_id)

    config = Config(
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", DEFAULT_CLIENT_ID),
        session_secret=secrets.token_urlsafe(32),
        site_origin=args.site_origin,
        secure_cookies=False,  # plain http on localhost
    )
    app = App(config, MemoryStore(), verify)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app, Path(args.data)))
    print(f"orbbits job dev backend on http://127.0.0.1:{args.port} (data from {args.data})")
    server.serve_forever()


if __name__ == "__main__":
    main()
