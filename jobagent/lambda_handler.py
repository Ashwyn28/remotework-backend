"""AWS Lambda entry point for the agent (function URL, payload format 2.0), reached through
CloudFront at /api/agent/.

No Anthropic API key exists anywhere: the function proves who it is with a short-lived token that
AWS STS signs for its execution role (outbound web identity federation), and Anthropic exchanges
that for access under a federation rule that trusts only this role. CloudFront's secret comes from
SSM Parameter Store once per cold start.
"""
import base64
import logging
import os
from functools import lru_cache

from .chat import Agent, Config, DynamoQuota, Limits

logging.getLogger().setLevel(logging.INFO)


@lru_cache(maxsize=1)
def _agent() -> Agent:
    import boto3

    ssm = boto3.client("ssm")

    def secret(name: str) -> str:
        return ssm.get_parameter(Name=os.environ[name], WithDecryption=True)["Parameter"]["Value"]

    config = Config(
        site_origin=os.environ["SITE_ORIGIN"],
        origin_secret=secret("ORIGIN_SECRET_PARAM"),
        limits=Limits(
            per_ip_per_day=int(os.environ.get("LIMIT_PER_IP_PER_DAY", "200")),
            site_per_day=int(os.environ.get("LIMIT_SITE_PER_DAY", "4000")),
        ),
    )
    return Agent(config, DynamoQuota(os.environ["QUOTA_TABLE"]), client=_claude())


ANTHROPIC_AUDIENCE = "https://api.anthropic.com"


def _claude():
    import anthropic
    import boto3
    from anthropic import WorkloadIdentityCredentials

    # GetWebIdentityToken is not on the STS global endpoint; use this region's
    sts = boto3.client("sts", region_name=os.environ["AWS_REGION"])

    def aws_token() -> str:
        # called again by the SDK whenever its Anthropic access token needs refreshing
        return sts.get_web_identity_token(
            Audience=[ANTHROPIC_AUDIENCE], SigningAlgorithm="RS256", DurationSeconds=300
        )["WebIdentityToken"]

    credentials = WorkloadIdentityCredentials(
        identity_token_provider=aws_token,
        federation_rule_id=os.environ["ANTHROPIC_FEDERATION_RULE_ID"],
        organization_id=os.environ["ANTHROPIC_ORGANIZATION_ID"],
        service_account_id=os.environ.get("ANTHROPIC_SERVICE_ACCOUNT_ID") or None,
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID") or None,
    )
    # a chat turn should be quick; one retry covers a dropped connection
    return anthropic.Anthropic(credentials=credentials, timeout=25.0, max_retries=1)


def viewer_ip(headers: dict[str, str], fallback: str) -> str:
    # CloudFront adds the viewer's address; the request's own source is the CloudFront edge
    address = headers.get("cloudfront-viewer-address", "")
    if address:
        return address.rsplit(":", 1)[0].strip("[]")
    forwarded = headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() if forwarded else fallback


def handler(event, context, agent: Agent | None = None):
    http = event["requestContext"]["http"]
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    reply = (agent or _agent()).handle(http["method"].upper(), headers, raw, viewer_ip(headers, http.get("sourceIp", "")))
    import json

    return {
        "statusCode": reply.status,
        "headers": {"Content-Type": "application/json", "Cache-Control": "no-store"},
        "body": json.dumps(reply.body),
    }
