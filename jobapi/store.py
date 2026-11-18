"""Where accounts live: DynamoDB in production, a dict in tests and local development."""
from __future__ import annotations

import json
from typing import Protocol


class UserStore(Protocol):
    def get(self, sub: str) -> dict | None: ...

    def put(self, user: dict) -> None: ...

    def delete(self, sub: str) -> None: ...


class MemoryStore:
    def __init__(self):
        self.users: dict[str, dict] = {}

    def get(self, sub: str) -> dict | None:
        user = self.users.get(sub)
        return json.loads(json.dumps(user)) if user else None  # a copy, like a real database

    def put(self, user: dict) -> None:
        self.users[user["sub"]] = json.loads(json.dumps(user))

    def delete(self, sub: str) -> None:
        self.users.pop(sub, None)


class DynamoStore:
    """One item per account, keyed by Google's account id.

    Answers and saved roles are stored as JSON strings so their shape round-trips exactly.
    """

    def __init__(self, table_name: str, table=None):
        if table is None:
            import boto3  # provided by the Lambda runtime

            table = boto3.resource("dynamodb").Table(table_name)
        self.table = table

    def get(self, sub: str) -> dict | None:
        item = self.table.get_item(Key={"sub": sub}, ConsistentRead=True).get("Item")
        if not item:
            return None
        return {
            "sub": item["sub"],
            "email": item.get("email", ""),
            "name": item.get("name", ""),
            "preferences": json.loads(item.get("preferences") or "{}"),
            "tracked": json.loads(item.get("tracked") or "{}"),
            "session_version": int(item.get("session_version", 1)),
            "created_at": item.get("created_at", ""),
            "updated_at": item.get("updated_at", ""),
        }

    def put(self, user: dict) -> None:
        self.table.put_item(
            Item={
                "sub": user["sub"],
                "email": user.get("email", ""),
                "name": user.get("name", ""),
                "preferences": json.dumps(user.get("preferences") or {}),
                "tracked": json.dumps(user.get("tracked") or {}),
                "session_version": int(user.get("session_version", 1)),
                "created_at": user.get("created_at", ""),
                "updated_at": user.get("updated_at", ""),
            }
        )

    def delete(self, sub: str) -> None:
        self.table.delete_item(Key={"sub": sub})
