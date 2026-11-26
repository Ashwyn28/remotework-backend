"""AWS Lambda entry point (function URL, payload format 2.0), reached through CloudFront.

Secrets come from SSM Parameter Store once per cold start, never from plain environment values.
"""
import base64
import logging
import os
from functools import lru_cache

from .app import App, Config, Request, parse_cookies
from .store import DynamoStore

logging.getLogger().setLevel(logging.INFO)


@lru_cache(maxsize=1)
def _app() -> App:
    import boto3

    ssm = boto3.client("ssm")

    def secret(name: str) -> str:
        return ssm.get_parameter(Name=os.environ[name], WithDecryption=True)["Parameter"]["Value"]

    config = Config(
        google_client_id=os.environ["GOOGLE_CLIENT_ID"],
        session_secret=secret("SESSION_SECRET_PARAM"),
        origin_secret=secret("ORIGIN_SECRET_PARAM"),
        site_origin=os.environ["SITE_ORIGIN"],
        secure_cookies=True,
    )
    return App(config, DynamoStore(os.environ["USERS_TABLE"]))


def to_request(event: dict) -> Request:
    http = event["requestContext"]["http"]
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    return Request(
        method=http["method"].upper(),
        path=event.get("rawPath") or http.get("path", "/"),
        headers=headers,
        cookies=parse_cookies(event.get("cookies") or []),
        body=raw,
    )


def handler(event, context, app: App | None = None):
    response = (app or _app()).handle(to_request(event))
    return {
        "statusCode": response.status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "cookies": response.cookies,
        "body": response.json(),
    }
