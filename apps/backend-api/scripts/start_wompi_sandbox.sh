#!/bin/sh
set -eu

# Fail closed: this entrypoint is only for the isolated Wompi Sandbox service.
[ "${ENVIRONMENT:-}" = "sandbox" ] || { echo "Refusing to start outside sandbox."; exit 1; }
[ "${WOMPI_ENVIRONMENT:-}" = "sandbox" ] || { echo "Refusing to use a non-sandbox Wompi environment."; exit 1; }
case "${DATABASE_URL:-}" in
  postgres://*|postgresql://*) ;;
  *) echo "Refusing to start unless using a dedicated PostgreSQL database."; exit 1 ;;
esac

if [ "${WOMPI_SANDBOX_SEED_NEW_DISPOSABLE:-false}" = "true" ]; then
  [ "${WOMPI_SANDBOX_SEED_DATA:-false}" = "true" ] || { echo "Explicit sandbox seed permission is required."; exit 1; }
  python scripts/check_empty_sandbox_database.py
fi
alembic upgrade head
if [ "${WOMPI_SANDBOX_SEED_NEW_DISPOSABLE:-false}" = "true" ]; then
  python scripts/seed_wompi_sandbox.py
fi
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"

