#!/bin/bash

PORT=${PORT:-8000}
WORKERS=${WORKERS:-1}

exec uv run uvicorn src.bootstrap:create_app --host 0.0.0.0 --port ${PORT} --reload --workers ${WORKERS} --factory