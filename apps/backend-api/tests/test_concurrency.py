"""
Pruebas de concurrencia real para CrediFresh sobre PostgreSQL.

Escenarios:
A. Dos desembolsos concurrentes del mismo crédito.
B. Dos pagos concurrentes válidos que completan la deuda.
C. Dos pagos concurrentes donde el segundo excede el saldo restante.

Importante:
- Usa exclusivamente credifresh_test_db.
- No usa la base de producción.
- No modifica tests/conftest.py.
- Cada hilo utiliza una sesión SQLAlchemy independiente.
- Los endpoints reales de desembolso y pago son ejecutados durante las pruebas.
"""

import os
import threading
import time
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

# ---------------------------------------------------------------------------
# 1. Configuración segura: SOLO PostgreSQL de pruebas
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")
TEST_DATABASE_NAME = "credifresh_test_db"

if not TEST_DATABASE_URL:
    pytest.fail(
        "Falta la variable POSTGRES_TEST_DATABASE_URL. "
        "Configúrala antes de ejecutar estos tests."
    )

try:
    test_database_url = make_url(TEST_DATABASE_URL)
except Exception as exc:
    pytest.fail(f"POSTGRES_TEST_DATABASE_URL no es válida: {exc}")

if (
    not test_database_url.drivername.startswith("postgresql")
    or test_database_url.host not in {"localhost", "127.0.0.1"}
    or test_database_url.port != 5434
    or test_database_url.database != TEST_DATABASE_NAME
):
    pytest.fail(
        "FATAL: la concurrencia solo puede ejecutarse en "
        "localhost:5434/credifresh_test_db, una instancia PostgreSQL aislada."
    )
# Hacemos que cualquier componente de la aplicación que lea DATABASE_URL
# durante este test use exclusivamente la base de pruebas.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

# ---------------------------------------------------------------------------
# 2. Importaciones de la aplicación
# ---------------------------------------------------------------------------

from app.models.usuario import Usuario
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.evaluacion import Evaluacion
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago
from app.models.aceptacion_credito import AceptacionCredito

from app.api.v1.endpoints.creditos import (
    desembolsar_credito_endpoint,
    registrar_pago_endpoint,
    PagoInputSchema,
)

from app.config.database import Base


# ---------------------------------------------------------------------------
# 3. Motor y sesiones independientes
# ---------------------------------------------------------------------------

test_engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
)

TestSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine,
)


# ---------------------------------------------------------------------------
# 4. Preparación y limpieza SOLO de credifresh_test_db
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def verify_test_database():
    with test_engine.connect() as conn:
        database_name = conn.execute(
            text("SELECT current_database()")
        ).scalar()

    assert database_name == TEST_DATABASE_NAME, (
        f"FATAL: el test está conectado a {database_name}, "
        "no a credifresh_test_db."
    )

    yield

    test_engine.dispose()


@pytest.fixture(autouse=True)
def clean_test_database():
    with test_engine.connect() as conn:
        database_name = conn.execute(
            text("SELECT current_database()")
        ).scalar()

        if database_name != "credifresh_test_db":
            pytest.fail(
                f"FATAL: intento de limpieza en base incorrecta: "
                f"{database_name}"
            )

        conn.execute(
            text(
                """
                TRUNCATE TABLE
                    pagos,
                    cuotas_amortizacion,
                    notificaciones,
                    evaluaciones,
                    creditos,
                    perfiles_financieros,
                    clientes,
                    audit_logs,
                    usuarios
                RESTART IDENTITY CASCADE
                """
            )
        )

        conn.commit()

    yield


# ---------------------------------------------------------------------------
# 5. Utilidades
# ---------------------------------------------------------------------------

def _new_session():
    """Devuelve una sesión completamente independiente."""
    return TestSessionLocal()


def _create_test_credit():
    """
    Crea directamente en PostgreSQL un crédito APROBADO con su evaluación.

    No se prueba aquí el motor de decisión.
    La finalidad de esta fase es probar exclusivamente la concurrencia
    de los endpoints de desembolso y pagos.
    """

    db = _new_session()

    try:
        unique = uuid4().hex[:10]

        # Usuario ADMIN utilizado por los endpoints para auditoría.
        usuario = Usuario(
            email=f"concurrency_admin_{unique}@credifresh.com",
            password_hash="test-password-hash",
            rol="ADMIN",
            activo=True,
        )

        db.add(usuario)
        db.flush()

        cliente_usuario = Usuario(
            email=f"concurrency_cliente_{unique}@credifresh.com",
            password_hash="test-password-hash",
            rol="CLIENTE",
            activo=True,
        )
        db.add(cliente_usuario)
        db.flush()

        # Asociar el CLIENTE para registrar su aceptación previa al desembolso.
        cliente = Cliente(
            nombre=f"Cliente Concurrencia {unique}",
            cedula=f"99{unique[:8]}",
            telefono="3000000000",
            usuario_id=cliente_usuario.id,
        )

        db.add(cliente)
        db.flush()

        # Crédito válido según las reglas actuales:
        # mínimo $500.000 y máximo $1.500.000.
        credito = Credito(
            cliente_id=cliente.id,
            monto=Decimal("500000.00"),
            plazo_meses=1,
            tasa_interes=Decimal("2.00"),
            estado="APROBADO",
        )

        db.add(credito)
        db.flush()

        # Para $500.000 a 2% mensual durante un mes:
        # cuota = $510.000.
        evaluacion = Evaluacion(
            credito_id=credito.id,
            decision="APROBADO",
            cuota_mensual=Decimal("510000.00"),
            capacidad_mensual=Decimal("4000000.00"),
            motivos="Prueba de concurrencia PostgreSQL",
        )

        db.add(evaluacion)
        db.flush()

        db.add(AceptacionCredito(
            credito_id=credito.id,
            cliente_id=cliente.id,
            usuario_id=cliente_usuario.id,
            monto=credito.monto,
            plazo_meses=credito.plazo_meses,
            tasa_interes=credito.tasa_interes,
            cuota_mensual=evaluacion.cuota_mensual,
            total_estimado=evaluacion.cuota_mensual,
            condiciones_version="1.0",
        ))

        db.commit()

        credito_id = credito.id
        usuario_id = usuario.id

        return credito_id, usuario_id

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def _get_user(db, usuario_id):
    usuario = (
        db.query(Usuario)
        .filter(Usuario.id == usuario_id)
        .first()
    )

    assert usuario is not None

    return usuario


def _wait_until_blocked(backend_pid, timeout=5.0):
    """
    Comprueba que PostgreSQL realmente está bloqueando la sesión.

    No utilizamos sleep como mecanismo de sincronización.
    Consultamos pg_blocking_pids() hasta comprobar el bloqueo real.
    """

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        with test_engine.connect() as observer:
            blocked = observer.execute(
                text(
                    """
                    SELECT cardinality(pg_blocking_pids(:pid)) > 0
                    """
                ),
                {"pid": backend_pid},
            ).scalar()

        if blocked:
            return True

        time.sleep(0.02)

    return False


def _disburse_credit_directly(credito_id, usuario_id):
    """
    Ejecuta el endpoint real de desembolso utilizando una sesión propia.
    """

    db = _new_session()

    try:
        usuario = _get_user(db, usuario_id)

        resultado = desembolsar_credito_endpoint(
            credito_id=credito_id,
            db=db,
            current_user=usuario,
        )

        return resultado

    finally:
        db.close()


def _create_disbursed_credit():
    """
    Crea y desembolsa un crédito usando el endpoint real.
    """

    credito_id, usuario_id = _create_test_credit()

    _disburse_credit_directly(
        credito_id=credito_id,
        usuario_id=usuario_id,
    )

    return credito_id, usuario_id


def _pay_credit(credito_id, usuario_id, monto, db=None):
    """
    Ejecuta el endpoint REAL de registro de pagos.
    """

    owns_session = db is None

    if owns_session:
        db = _new_session()

    try:
        usuario = _get_user(db, usuario_id)

        pago_data = PagoInputSchema(
            monto=Decimal(monto),
            metodo_pago="TRANSFERENCIA",
        )

        return registrar_pago_endpoint(
            credito_id=credito_id,
            pago_data=pago_data,
            db=db,
            current_user=usuario,
        )

    finally:
        if owns_session:
            db.close()


# ---------------------------------------------------------------------------
# 6. PRUEBA A
#    Dos desembolsos concurrentes del mismo crédito
# ---------------------------------------------------------------------------

def test_concurrent_double_disbursement():
    """
    Verifica que dos operaciones concurrentes sobre el mismo crédito
    quedan serializadas mediante FOR UPDATE.

    Resultado esperado:
    - La sesión A obtiene el lock.
    - La sesión B queda realmente bloqueada.
    - A desembolsa y hace COMMIT.
    - B se desbloquea.
    - B vuelve a leer el crédito como DESEMBOLSADO.
    - B recibe HTTP 400.
    - Existe exactamente un plan de amortización.
    """

    credito_id, usuario_id = _create_test_credit()

    session_a = _new_session()

    try:
        usuario_a = _get_user(session_a, usuario_id)

        # A obtiene el bloqueo exclusivo.
        credito_a = (
            session_a.query(Credito)
            .filter(Credito.id == credito_id)
            .with_for_update()
            .first()
        )

        assert credito_a is not None
        assert credito_a.estado == "APROBADO"

        resultado_b = {}
        started_b = threading.Event()

        def worker_b():
            db_b = _new_session()

            try:
                backend_pid = db_b.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar()

                resultado_b["backend_pid"] = backend_pid
                started_b.set()

                try:
                    desembolsar_credito_endpoint(
                        credito_id=credito_id,
                        db=db_b,
                        current_user=_get_user(db_b, usuario_id),
                    )

                    resultado_b["success"] = True

                except Exception as exc:
                    resultado_b["success"] = False
                    resultado_b["exception"] = exc

            finally:
                db_b.rollback()
                db_b.close()

        thread_b = threading.Thread(
            target=worker_b,
            name="concurrency-disbursement-B",
        )

        thread_b.start()

        assert started_b.wait(timeout=5), (
            "La sesión B no llegó a iniciar."
        )

        backend_pid_b = resultado_b["backend_pid"]

        # Confirmamos que B está realmente bloqueada por A.
        assert _wait_until_blocked(backend_pid_b), (
            "PostgreSQL no reportó a la sesión B como bloqueada."
        )

        # A ejecuta el endpoint REAL utilizando la misma sesión que posee
        # el lock.
        resultado_a = desembolsar_credito_endpoint(
            credito_id=credito_id,
            db=session_a,
            current_user=usuario_a,
        )

        assert resultado_a["mensaje"] == (
            "Crédito desembolsado correctamente"
        )

        # El endpoint ya hizo COMMIT.
        thread_b.join(timeout=5)

        assert not thread_b.is_alive(), (
            "La sesión B no se desbloqueó después del COMMIT de A."
        )

        assert resultado_b["success"] is False
        assert isinstance(
            resultado_b["exception"],
            HTTPException,
        )

        assert resultado_b["exception"].status_code == 400

    finally:
        session_a.rollback()
        session_a.close()

    # Verificación final independiente.
    verify = _new_session()

    try:
        credito_final = (
            verify.query(Credito)
            .filter(Credito.id == credito_id)
            .first()
        )

        assert credito_final is not None
        assert credito_final.estado == "DESEMBOLSADO"

        numero_cuotas = (
            verify.query(CuotaAmortizacion)
            .filter(
                CuotaAmortizacion.credito_id == credito_id
            )
            .count()
        )

        assert numero_cuotas == 1

    finally:
        verify.close()


# ---------------------------------------------------------------------------
# 7. PRUEBA B
#    Dos pagos concurrentes válidos
# ---------------------------------------------------------------------------

def test_concurrent_valid_payments():
    """
    Verifica que dos pagos concurrentes válidos se procesan
    secuencialmente mediante el lock del crédito y de las cuotas.

    Deuda inicial: $510.000.

    A paga: $300.000.
    B paga: $210.000.

    Resultado esperado:
    - B queda bloqueada mientras A procesa.
    - A hace COMMIT.
    - B continúa.
    - B observa el saldo actualizado de $210.000.
    - Ambos pagos son exitosos.
    - El crédito termina PAGADO.
    """

    credito_id, usuario_id = _create_disbursed_credit()

    session_a = _new_session()

    try:
        usuario_a = _get_user(session_a, usuario_id)

        # A bloquea el crédito.
        credito_a = (
            session_a.query(Credito)
            .filter(Credito.id == credito_id)
            .with_for_update()
            .first()
        )

        assert credito_a is not None
        assert credito_a.estado == "DESEMBOLSADO"

        # A bloquea también las cuotas, igual que el endpoint real.
        cuotas_a = (
            session_a.query(CuotaAmortizacion)
            .filter(
                CuotaAmortizacion.credito_id == credito_id
            )
            .with_for_update()
            .all()
        )

        assert len(cuotas_a) == 1

        resultado_b = {}
        started_b = threading.Event()

        def worker_b():
            db_b = _new_session()

            try:
                backend_pid = db_b.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar()

                resultado_b["backend_pid"] = backend_pid
                started_b.set()

                try:
                    pago_data = PagoInputSchema(
                        monto=Decimal("210000.00"),
                        metodo_pago="TRANSFERENCIA",
                    )

                    resultado_b["response"] = registrar_pago_endpoint(
                        credito_id=credito_id,
                        pago_data=pago_data,
                        db=db_b,
                        current_user=_get_user(
                            db_b,
                            usuario_id,
                        ),
                    )

                    resultado_b["success"] = True

                except Exception as exc:
                    resultado_b["success"] = False
                    resultado_b["exception"] = exc

            finally:
                db_b.rollback()
                db_b.close()

        thread_b = threading.Thread(
            target=worker_b,
            name="concurrency-payment-B",
        )

        thread_b.start()

        assert started_b.wait(timeout=5)

        backend_pid_b = resultado_b["backend_pid"]

        # B debe estar realmente bloqueada por A.
        assert _wait_until_blocked(backend_pid_b), (
            "PostgreSQL no reportó el bloqueo de B durante el pago."
        )

        # A ejecuta el endpoint REAL con la sesión que ya posee los locks.
        pago_a = PagoInputSchema(
            monto=Decimal("300000.00"),
            metodo_pago="TRANSFERENCIA",
        )

        resultado_a = registrar_pago_endpoint(
            credito_id=credito_id,
            pago_data=pago_a,
            db=session_a,
            current_user=usuario_a,
        )

        assert resultado_a["mensaje"] == (
            "Pago procesado y aplicado correctamente"
        )

        thread_b.join(timeout=5)

        assert not thread_b.is_alive(), (
            "La sesión B no se desbloqueó después del pago de A."
        )

        assert resultado_b["success"] is True

    finally:
        session_a.rollback()
        session_a.close()

    # Verificación final independiente.
    verify = _new_session()

    try:
        credito_final = (
            verify.query(Credito)
            .filter(Credito.id == credito_id)
            .first()
        )

        assert credito_final is not None
        assert credito_final.estado == "PAGADO"

        pagos = (
            verify.query(Pago)
            .filter(Pago.credito_id == credito_id)
            .all()
        )

        assert len(pagos) == 2

        total_pagado = sum(
            (Decimal(p.monto_pagado) for p in pagos),
            Decimal("0.00"),
        )

        assert total_pagado == Decimal("510000.00")

        cuota = (
            verify.query(CuotaAmortizacion)
            .filter(
                CuotaAmortizacion.credito_id == credito_id
            )
            .first()
        )

        assert cuota is not None
        assert Decimal(cuota.monto_pagado) == Decimal("510000.00")

    finally:
        verify.close()


# ---------------------------------------------------------------------------
# 8. PRUEBA C
#    Segundo pago concurrente excede el saldo restante
# ---------------------------------------------------------------------------

def test_concurrent_payment_exceeding_remaining_balance():
    """
    Verifica que el segundo pago no pueda exceder el saldo real
    después de que el primer pago se compromete.

    Deuda inicial: $510.000.

    A paga: $300.000.
    Saldo real posterior: $210.000.

    B intenta pagar: $300.000.

    Resultado esperado:
    - B queda bloqueada.
    - A hace COMMIT.
    - B continúa.
    - B calcula la deuda real de $210.000.
    - B recibe HTTP 400.
    - Solo existe un pago de $300.000.
    """

    credito_id, usuario_id = _create_disbursed_credit()

    session_a = _new_session()

    try:
        usuario_a = _get_user(session_a, usuario_id)

        # A bloquea el crédito.
        credito_a = (
            session_a.query(Credito)
            .filter(Credito.id == credito_id)
            .with_for_update()
            .first()
        )

        assert credito_a is not None
        assert credito_a.estado == "DESEMBOLSADO"

        # A bloquea las cuotas.
        cuotas_a = (
            session_a.query(CuotaAmortizacion)
            .filter(
                CuotaAmortizacion.credito_id == credito_id
            )
            .with_for_update()
            .all()
        )

        assert len(cuotas_a) == 1

        resultado_b = {}
        started_b = threading.Event()

        def worker_b():
            db_b = _new_session()

            try:
                backend_pid = db_b.execute(
                    text("SELECT pg_backend_pid()")
                ).scalar()

                resultado_b["backend_pid"] = backend_pid
                started_b.set()

                try:
                    pago_b = PagoInputSchema(
                        monto=Decimal("300000.00"),
                        metodo_pago="TRANSFERENCIA",
                    )

                    registrar_pago_endpoint(
                        credito_id=credito_id,
                        pago_data=pago_b,
                        db=db_b,
                        current_user=_get_user(
                            db_b,
                            usuario_id,
                        ),
                    )

                    resultado_b["success"] = True

                except Exception as exc:
                    resultado_b["success"] = False
                    resultado_b["exception"] = exc

            finally:
                db_b.rollback()
                db_b.close()

        thread_b = threading.Thread(
            target=worker_b,
            name="concurrency-payment-invalid-B",
        )

        thread_b.start()

        assert started_b.wait(timeout=5)

        backend_pid_b = resultado_b["backend_pid"]

        # Confirmar bloqueo real.
        assert _wait_until_blocked(backend_pid_b), (
            "PostgreSQL no reportó el bloqueo de B."
        )

        # A realiza el pago REAL de $300.000.
        pago_a = PagoInputSchema(
            monto=Decimal("300000.00"),
            metodo_pago="TRANSFERENCIA",
        )

        resultado_a = registrar_pago_endpoint(
            credito_id=credito_id,
            pago_data=pago_a,
            db=session_a,
            current_user=usuario_a,
        )

        assert resultado_a["mensaje"] == (
            "Pago procesado y aplicado correctamente"
        )

        thread_b.join(timeout=5)

        assert not thread_b.is_alive(), (
            "La sesión B no se desbloqueó después del COMMIT de A."
        )

        # B debe haber fallado por exceso de pago.
        assert resultado_b["success"] is False
        assert isinstance(
            resultado_b["exception"],
            HTTPException,
        )

        assert resultado_b["exception"].status_code == 400

    finally:
        session_a.rollback()
        session_a.close()

    # Verificación final independiente.
    verify = _new_session()

    try:
        credito_final = (
            verify.query(Credito)
            .filter(Credito.id == credito_id)
            .first()
        )

        assert credito_final is not None
        assert credito_final.estado == "DESEMBOLSADO"

        pagos = (
            verify.query(Pago)
            .filter(Pago.credito_id == credito_id)
            .all()
        )

        # Solo A pudo registrar el pago.
        assert len(pagos) == 1
        assert Decimal(pagos[0].monto_pagado) == Decimal("300000.00")

        cuota = (
            verify.query(CuotaAmortizacion)
            .filter(
                CuotaAmortizacion.credito_id == credito_id
            )
            .first()
        )

        assert cuota is not None

        # Saldo pendiente:
        # 510.000 - 300.000 = 210.000
        deuda_restante = (
            Decimal(cuota.monto_cuota)
            - Decimal(cuota.monto_pagado)
        )

        assert deuda_restante == Decimal("210000.00")

    finally:
        verify.close()
