#!/bin/sh
set -eu

PORT_VALUE="${PORT:-8000}"
RUN_MIGRATIONS_VALUE="${RUN_DB_MIGRATIONS:-true}"

if [ "${RUN_MIGRATIONS_VALUE}" = "true" ]; then
  alembic upgrade head
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT_VALUE}" --proxy-headers --forwarded-allow-ips="*"
