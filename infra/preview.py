"""Serve the production build the way CloudFront will, to check it before deploying.

    python -m jobapi.devserver --site-origin http://localhost:4173 --port 8788 &
    python infra/preview.py --build ../remotework/build --backend http://127.0.0.1:8788

- App routes without a file extension get the app shell (the same rule as the CloudFront function).
- /api, /data and /static go to the backend, as CloudFront routes them.
- Every response carries the security headers from infra/terraform/cdn.tf; keep the two in step.
"""
import argparse
import mimetypes
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# mirrors aws_cloudfront_response_headers_policy.security
SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/client",
            "style-src 'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
            "img-src 'self' data: https:",
            "font-src 'self' data:",
            "connect-src 'self' https://accounts.google.com/gsi/",
            "frame-src https://accounts.google.com/gsi/",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
        ]
    ),
}
FORWARDED = ("/api/", "/data/", "/static/")
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "content-length", "content-encoding"}


def make_handler(build: Path, backend: str):
    build = build.resolve()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status, headers, body):
            self.send_response(status)
            for name, value in headers:
                if name.lower() not in HOP_BY_HOP:
                    self.send_header(name, value)
            for name, value in SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _forward(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            request = urllib.request.Request(backend + self.path, data=body, method=method)  # noqa: S310
            for name, value in self.headers.items():
                if name.lower() not in ("host", "content-length", "accept-encoding"):
                    request.add_header(name, value)
            try:
                with urllib.request.urlopen(request) as response:  # noqa: S310 - local backend
                    self._send(response.status, response.headers.items(), response.read())
            except urllib.error.HTTPError as error:
                self._send(error.code, error.headers.items(), error.read())

        def _static(self):
            path = self.path.split("?", 1)[0]
            if "." not in path.rsplit("/", 1)[-1]:
                path = "/index.html"  # the CloudFront function's rule
            file = (build / path.lstrip("/")).resolve()
            if build not in file.parents or not file.is_file():
                self._send(403, [("Content-Type", "text/plain")], b"Forbidden")  # what S3 returns
                return
            kind = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            self._send(200, [("Content-Type", kind)], file.read_bytes())

        def do_GET(self):  # noqa: N802
            self._forward("GET") if self.path.startswith(FORWARDED) else self._static()

        def do_POST(self):  # noqa: N802
            self._forward("POST")

        def do_PUT(self):  # noqa: N802
            self._forward("PUT")

        def do_DELETE(self):  # noqa: N802
            self._forward("DELETE")

    return Handler


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="../remotework/build")
    parser.add_argument("--backend", default="http://127.0.0.1:8788")
    parser.add_argument("--port", type=int, default=4173)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(Path(args.build), args.backend))
    print(f"Preview on http://localhost:{args.port}")
    server.serve_forever()
