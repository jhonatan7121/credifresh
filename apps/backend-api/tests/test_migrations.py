"""Regression test for the Alembic initial schema."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "alembic_version",
    "auth_rate_limit_windows",
    "audit_logs",
    "aceptaciones_credito",
    "cotizaciones_aceptadas",
    "clientes",
    "creditos",
    "cuotas_amortizacion",
    "evaluaciones",
    "notificaciones",
    "pagos",
    "perfiles_financieros",
    "usuarios",
    "tasas_credito_mensuales",
    "wompi_pagos",
    "wompi_reembolsos_sandbox",
    "wompi_desembolsos_sandbox",
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
                payout_indexes = {
                    row[1]: row[2]
                    for row in connection.execute("PRAGMA index_list('wompi_desembolsos_sandbox')")
                }
                self.assertEqual(payout_indexes.get("ix_wompi_desembolsos_sandbox_credito_id"), 1)
                self.assertEqual(payout_indexes.get("ix_wompi_desembolsos_sandbox_payout_id"), 1)
                payment_indexes = {row[1]: row[2] for row in connection.execute("PRAGMA index_list('wompi_pagos')")}
                self.assertEqual(payment_indexes.get("uq_wompi_pago_cuota_abierto"), 1)
                refund_unique = [row for row in connection.execute("PRAGMA index_list('wompi_reembolsos_sandbox')") if row[2]]
                self.assertGreaterEqual(len(refund_unique), 2)
            finally:
                connection.close()

        self.assertSetEqual(tables, EXPECTED_TABLES)

    def test_no_pierde_reembolsos_al_revertir_migracion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "refund-migration.sqlite3"
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
            command = [sys.executable, "-m", "alembic", "-c", "alembic.ini"]
            subprocess.run(command + ["upgrade", "head"], cwd=BACKEND_DIRECTORY, env=environment, check=True)
            with closing(sqlite3.connect(database_path)) as connection:
                connection.execute("""INSERT INTO wompi_reembolsos_sandbox
                    (wompi_pago_id, referencia, monto, escenario, estado)
                    VALUES (1, 'ref-prueba', 100, 'approved', 'INCIERTO')""")
                connection.commit()
            result = subprocess.run(command + ["downgrade", "-1"], cwd=BACKEND_DIRECTORY, env=environment,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no se puede perder su trazabilidad", result.stderr)
            with closing(sqlite3.connect(database_path)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM wompi_reembolsos_sandbox").fetchone()[0], 1)

    def test_migration_rechaza_intentos_abiertos_duplicados(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / "migration-duplicates.sqlite3"
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
            base_command = [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade"]
            subprocess.run(base_command + ["12da730bf081"], cwd=BACKEND_DIRECTORY, env=environment, check=True)
            with closing(sqlite3.connect(database_path)) as connection:
                for i in (1, 2):
                    connection.execute("""INSERT INTO wompi_pagos
                        (credito_id, cuota_id, referencia, wompi_link_id, monto_esperado, estado, checkout_url)
                        VALUES (1, 1, ?, ?, 1250, 'PENDIENTE', ?)""", (f"ref-{i}", f"link-{i}", f"url-{i}"))
                connection.commit()
            result = subprocess.run(base_command + ["head"], cwd=BACKEND_DIRECTORY, env=environment,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("múltiples intentos abiertos", result.stderr)
