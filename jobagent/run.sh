#!/bin/bash
# Lambda handler for the streaming agent: the Lambda Web Adapter layer (AWS_LAMBDA_EXEC_WRAPPER=
# /opt/bootstrap) starts this, waits for GET / to answer, then relays requests and streams replies.
PATH=$PATH:$LAMBDA_TASK_ROOT/bin \
PYTHONPATH=$PYTHONPATH:$LAMBDA_TASK_ROOT:$LAMBDA_RUNTIME_DIR \
exec python -m uvicorn --host 127.0.0.1 --port "${PORT:-8080}" --no-access-log jobagent.server:app
