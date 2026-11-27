"""The agent as a small web app, for streaming replies.

Lambda streams responses only through its function URL in RESPONSE_STREAM mode. AWS's Lambda Web
Adapter layer runs this app (see run.sh) and passes the stream through. Same checks, model and
limits as the buffered handler in lambda_handler.py.
"""
from __future__ import annotations

import logging

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, StreamingResponse
from starlette.routing import Route

from .chat import Reply
from .lambda_handler import _agent, viewer_ip

# stdout goes to CloudWatch; keep the per-turn token counts the buffered handler logged
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
NO_STORE = {"Cache-Control": "no-store"}


async def chat(request: Request):
    headers = {name.lower(): value for name, value in request.headers.items()}
    body = await request.body()
    agent = request.app.state.agent_factory()
    client_ip = request.client.host if request.client else ""
    admitted = agent.admit(request.method, headers, body, viewer_ip(headers, client_ip))
    if isinstance(admitted, Reply):
        return JSONResponse(admitted.body, status_code=admitted.status, headers=NO_STORE)
    return StreamingResponse(
        agent.stream(admitted),  # a plain iterator: Starlette runs it in a worker thread
        media_type="application/x-ndjson",
        headers={**NO_STORE, "X-Accel-Buffering": "no"},
    )


async def ready(request: Request):
    # the adapter waits for this before passing on the first request
    return PlainTextResponse("ok")


def create_app(agent_factory=_agent) -> Starlette:
    app = Starlette(
        routes=[
            Route("/", ready, methods=["GET"]),
            Route("/api/agent", chat, methods=["POST"]),
            Route("/api/agent/", chat, methods=["POST"]),
        ]
    )
    app.state.agent_factory = agent_factory
    return app


app = create_app()
