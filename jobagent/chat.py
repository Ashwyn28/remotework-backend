"""One turn of the job-search agent: check the request, check the spending limits, ask Claude.

    POST /api/agent/   {"messages": [...]}  ->  {"content": [...], "stop_reason": "..."}

The browser keeps the conversation and runs the tools; this endpoint relays one model call at a
time. Everything that costs money is fixed here: model, system prompt, tools, output cap. The
request may carry only user and assistant turns made of text, tool calls, tool results and the
model's own thinking blocks, within size limits.
"""
from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .prompt import MODEL, SYSTEM, TOOLS

log = logging.getLogger(__name__)

MAX_BODY = 200 * 1024
MAX_MESSAGES = 60
MAX_USER_TEXT = 4000
MAX_TOOL_RESULT = 40000  # a CV plus a shortlist of roles
MAX_OUTPUT_TOKENS = 4096  # thinking counts towards this, so leave room above the reply itself
ALLOWED_BLOCKS = {
    "user": {"text", "tool_result"},
    "assistant": {"text", "tool_use", "thinking", "redacted_thinking"},
}
ORIGIN_HEADER = "x-origin-verify"


@dataclass(frozen=True)
class Limits:
    per_ip_per_day: int = 200
    site_per_day: int = 4000


@dataclass(frozen=True)
class Config:
    site_origin: str
    origin_secret: str = ""  # CloudFront's header; empty when running locally
    limits: Limits = Limits()


class Quota(Protocol):
    def take(self, key: str, limit: int, day: str) -> bool:
        """Count one request against `key` for `day`; False once `limit` is reached."""


class MemoryQuota:
    def __init__(self):
        self.counts: dict[tuple[str, str], int] = {}

    def take(self, key: str, limit: int, day: str) -> bool:
        used = self.counts.get((key, day), 0)
        if used >= limit:
            return False
        self.counts[(key, day)] = used + 1
        return True


class DynamoQuota:
    """Daily counters in DynamoDB, one item per key and day, expiring two days later."""

    def __init__(self, table_name: str, table=None):
        if table is None:
            import boto3  # provided by the Lambda runtime

            table = boto3.resource("dynamodb").Table(table_name)
        self.table = table

    def take(self, key: str, limit: int, day: str) -> bool:
        from botocore.exceptions import ClientError

        expires = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) + 2 * 86400
        try:
            self.table.update_item(
                Key={"k": f"{key}#{day}"},
                UpdateExpression="ADD n :one SET expires_at = :exp",
                ConditionExpression="attribute_not_exists(n) OR n < :limit",
                ExpressionAttributeValues={":one": 1, ":limit": limit, ":exp": expires},
            )
            return True
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise


@dataclass
class Reply:
    status: int
    body: dict


class BadRequest(ValueError):
    pass


def validate(body: bytes) -> list[dict]:
    if len(body) > MAX_BODY:
        raise BadRequest("conversation too long")
    try:
        data = json.loads(body or b"{}")
    except ValueError as error:
        raise BadRequest("body is not JSON") from error
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list) or not messages:
        raise BadRequest("messages must be a non-empty list")
    if len(messages) > MAX_MESSAGES:
        raise BadRequest("conversation too long")
    if messages[0].get("role") != "user" or messages[-1].get("role") != "user":
        raise BadRequest("conversation must start and end with the person")

    clean = []
    for message in messages:
        role = message.get("role") if isinstance(message, dict) else None
        if role not in ALLOWED_BLOCKS:
            raise BadRequest("unknown role")
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list) or not content:
            raise BadRequest("message content must be text or a list of blocks")
        for block in content:
            kind = block.get("type") if isinstance(block, dict) else None
            if kind not in ALLOWED_BLOCKS[role]:
                raise BadRequest(f"{kind} blocks are not allowed in {role} messages")
            if role == "user" and kind == "text" and len(str(block.get("text", ""))) > MAX_USER_TEXT:
                raise BadRequest("message too long")
            if kind == "tool_result" and len(json.dumps(block.get("content", ""))) > MAX_TOOL_RESULT:
                raise BadRequest("tool result too long")
        # passed through exactly as received: thinking blocks must come back unchanged
        clean.append({"role": role, "content": content})
    return clean


# Judging a CV against a shortlist of roles is worth more thought than chat and simple searches.
CAREFUL_TOOLS = {"find_cv_matches"}


def effort_for(messages: list[dict]) -> str:
    """'medium' when this turn answers a careful tool's call, else 'low'."""
    if len(messages) < 2 or messages[-2].get("role") != "assistant":
        return "low"
    answered = {
        block.get("tool_use_id")
        for block in messages[-1]["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    }
    careful = any(
        block.get("type") == "tool_use" and block.get("id") in answered and block.get("name") in CAREFUL_TOOLS
        for block in messages[-2]["content"]
        if isinstance(block, dict)
    )
    return "medium" if careful else "low"


class Agent:
    def __init__(self, config: Config, quota: Quota, client=None, today=None):
        self.config = config
        self.quota = quota
        self._client = client
        self._today = today or (lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    @property
    def client(self):
        if self._client is None:
            import anthropic

            # a chat turn should be quick; one retry covers a dropped connection
            self._client = anthropic.Anthropic(timeout=25.0, max_retries=1)
        return self._client

    def handle(self, method: str, headers: dict[str, str], body: bytes, ip: str) -> Reply:
        if self.config.origin_secret and not hmac.compare_digest(
            headers.get(ORIGIN_HEADER, ""), self.config.origin_secret
        ):
            return Reply(403, {"error": "forbidden"})
        if method != "POST":
            return Reply(405, {"error": "method not allowed"})
        # only the site's own pages may spend the budget
        if headers.get("origin") != self.config.site_origin:
            return Reply(403, {"error": "forbidden"})
        try:
            messages = validate(body)
        except BadRequest as error:
            return Reply(400, {"error": str(error)})

        day = self._today()
        if not self.quota.take(f"ip:{ip}", self.config.limits.per_ip_per_day, day):
            return Reply(429, {"error": "daily limit reached", "scope": "you"})
        if not self.quota.take("site", self.config.limits.site_per_day, day):
            return Reply(429, {"error": "daily limit reached", "scope": "site"})

        return self._ask(messages, effort_for(messages))

    def _ask(self, messages: list[dict], effort: str = "low") -> Reply:
        import anthropic

        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_OUTPUT_TOKENS,
                system=SYSTEM,
                tools=TOOLS,
                messages=messages,
                output_config={"effort": effort},
                cache_control={"type": "ephemeral"},  # reuse the system prompt, tools and history
            )
        except anthropic.BadRequestError as error:
            log.warning("model rejected the request: %s", error.message)
            return Reply(400, {"error": "the conversation could not be continued"})
        except anthropic.RateLimitError:
            return Reply(503, {"error": "busy, try again shortly"})
        except anthropic.APIStatusError as error:
            log.error("model error %s: %s", error.status_code, error.message)
            return Reply(502, {"error": "the assistant is unavailable"})
        except anthropic.APIConnectionError:
            log.error("could not reach the model")
            return Reply(502, {"error": "the assistant is unavailable"})

        usage = response.usage
        log.info(
            "turn stop=%s in=%s cache_read=%s out=%s",
            response.stop_reason, usage.input_tokens, usage.cache_read_input_tokens, usage.output_tokens,
        )
        return Reply(
            200,
            {
                "content": response.to_dict()["content"],
                "stop_reason": response.stop_reason,
            },
        )
