"""Regression test for the Alembic initial schema."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "alembic_version",
    "audit_logs",
    "clientes",
    "creditos",
    "cuotas_amortizacion",
    "evaluaciones",
    "notificaciones",
    "pagos",
    "perfiles_financieros",
    "usuarios",
}


class InitialMigrationTests(unittest.TestCase):
    def test_upgrade_head_creates_the_expected_schema(self) -> None:
        """A fresh database can be upgraded without accessing application data."""
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "migration-test.sqlite3"
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"

            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "alembic",
                    "-c",
                    "alembic.ini",
                    "upgrade",
                    "head",
                ],
                cwd=BACKEND_DIRECTORY,
                env=environment,
                check=True,
            )

            connection = sqlite3.connect(database_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()

        self.assertSetEqual(tables, EXPECTED_TABLES)
