#!/bin/sh
set -eu

# Fail closed: this entrypoint is only for the isolated, disposable test service.
[ "${ENVIRONMENT:-}" = "sandbox" ] || { echo "Refusing to start outside sandbox."; exit 1; }
[ "${WOMPI_ENVIRONMENT:-}" = "sandbox" ] || { echo "Refusing to use a non-sandbox Wompi environment."; exit 1; }
[ "${WOMPI_SANDBOX_SEED_DATA:-}" = "true" ] || { echo "Sandbox seed flag is required."; exit 1; }
case "${DATABASE_URL:-}" in
  sqlite:////tmp/credifresh-wompi-sandbox.db) ;;
  *) echo "Refusing to start unless using the disposable /tmp SQLite database."; exit 1 ;;
esac

alembic upgrade head
python scripts/seed_wompi_sandbox.py
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8000}"

