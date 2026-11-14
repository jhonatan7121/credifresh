"""Etapas administrativas de reembolsos: sin movimientos de cartera ni envíos."""
import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker
from app.models.audit_log import AuditLog
from app.models.pago import Pago
from app.models.solicitud_reembolso import SolicitudReembolsoSandbox
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.wompi_reembolso import WompiReembolsoSandbox
from app.services.wompi_service import consultar_transaccion, consultar_reembolso_sandbox, get_wompi_environment, verificar_configuracion_recaudo, solicitar_reembolso_sandbox
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(prefix="/integraciones/wompi/sandbox/solicitudes-reembolso", tags=["Reembolsos Sandbox"])
logger = logging.getLogger(__name__)
ADMIN = RoleChecker(["ADMIN"])


def exigir_habilitado():
    if (os.getenv("ENVIRONMENT", "").strip().lower() != "sandbox"
            or os.getenv("WOMPI_SANDBOX_REFUND_POLICY_ENABLED", "false").strip().lower() != "true"
            or get_wompi_environment() != "sandbox"):
        raise HTTPException(status_code=404, detail="Funcionalidad no disponible.")
    verificar_configuracion_recaudo()


class NuevaSolicitud(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    wompi_pago_id: int = Field(gt=0)
    monto_centavos: int = Field(gt=0, strict=True, le=999999999999)
    motivo: Literal["PAGO_DUPLICADO", "PAGO_EN_EXCESO", "INTERESES_INDEBIDOS", "REVERSO_PAGO", "ERROR_OPERATIVO", "OTRO"]
    descripcion: str = Field(min_length=10, max_length=2000)
    clasificacion: Literal["PASIVO_SALDO_A_FAVOR", "AJUSTE_INTERESES", "REVERSO_CAPITAL_POR_REVISAR", "OTRO_TRATAMIENTO_PENDIENTE"]
    evidencia: str = Field(min_length=3, max_length=250)

    @model_validator(mode="after")
    def detalle_otro(self):
        if self.motivo == "OTRO" and len(self.descripcion) < 30:
            raise ValueError("OTRO requiere una explicación de al menos 30 caracteres.")
        return self


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    decision: Literal["APROBADA", "RECHAZADA"]
    justificacion: str = Field(min_length=10, max_length=2000)


class RevisionContable(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    resultado: Literal["PENDIENTE", "APROBADA", "RECHAZADA"]
    observacion: str = Field(min_length=10, max_length=2000)


class ConsultaProveedor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refund_id: str = Field(min_length=1, max_length=15, pattern=r"^[0-9]+$")


def version(s):
    values = [s.wompi_pago_id, s.pago_id, s.credito_id, s.cuota_id, s.transaccion_id,
              s.monto_centavos, s.motivo, s.descripcion, s.clasificacion, s.evidencia]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def obtener(db, solicitud_id, lock=False):
    query = db.query(SolicitudReembolsoSandbox).filter_by(id=solicitud_id)
    s = (query.with_for_update() if lock else query).first()
    if not s:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
    return s


def resumen(s):
    return {"id": s.id, "credito_id": s.credito_id, "cuota_id": s.cuota_id,
            "pago_id": s.pago_id, "wompi_pago_id": s.wompi_pago_id, "transaccion_id": s.transaccion_id,
            "monto_centavos": s.monto_centavos, "motivo": s.motivo,
            "descripcion": s.descripcion, "clasificacion": s.clasificacion,
            "evidencia": s.evidencia, "solicitante_id": s.solicitante_id,
            "creada_en": s.creada_en, "autorizacion": s.autorizacion,
            "aprobador_id": s.aprobador_id, "decidida_en": s.decidida_en,
            "justificacion": s.justificacion, "ejecucion": s.ejecucion,
            "verificacion": s.verificacion, "conciliacion": s.conciliacion,
            "revision_contable": s.revision_contable, "observacion_contable": s.observacion_contable,
            "reembolso_id": s.reembolso_id, "cerrada_en": s.cerrada_en,
            "distribucion_pago_verificada": False, "cartera_modificada": False,
            "conciliacion_bancaria_real": False, "ambiente": "sandbox"}


def auditar(db, user, s, accion, detalles=None):
    registrar_auditoria(db, user, accion, "solicitud_reembolso_sandbox", s.id, detalles=detalles)


@router.post("", status_code=201)
def crear(datos: NuevaSolicitud, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    attempt = db.query(WompiPago).filter_by(id=datos.wompi_pago_id).first()
    if not attempt or attempt.estado != "PAGADO" or not attempt.wompi_transaction_id or not attempt.wompi_link_id:
        raise HTTPException(status_code=409, detail="Pago Wompi confirmado no encontrado.")
    if (db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=attempt.id).first()
            or db.query(SolicitudReembolsoSandbox).filter_by(wompi_pago_id=attempt.id).first()):
        raise HTTPException(status_code=409, detail="Ya existe un reembolso o una solicitud para este pago.")
    pagos = db.query(Pago).filter_by(credito_id=attempt.credito_id, cuota_id=attempt.cuota_id, metodo_pago="WOMPI_SANDBOX").all()
    monto = Decimal(str(attempt.monto_esperado))
    centavos = monto * 100
    if (len(pagos) != 1 or Decimal(str(pagos[0].monto_pagado)) != monto
            or centavos != centavos.to_integral_value() or datos.monto_centavos > centavos):
        raise HTTPException(status_code=409, detail="Los pagos o el importe requieren revisión.")
    transaction_id, link_id, original_amount = attempt.wompi_transaction_id, attempt.wompi_link_id, monto
    # Release the read transaction before the external request; reacquire and
    # validate all mutable payment state after the provider responds.
    db.rollback()
    txn = consultar_transaccion(transaction_id)
    attempt = db.query(WompiPago).filter_by(id=datos.wompi_pago_id).with_for_update().first()
    if (not attempt or attempt.estado != "PAGADO" or attempt.wompi_transaction_id != transaction_id
            or attempt.wompi_link_id != link_id or Decimal(str(attempt.monto_esperado)) != original_amount):
        raise HTTPException(status_code=409, detail="El pago cambió durante la validación; requiere revisión.")
    if (db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=attempt.id).first()
            or db.query(SolicitudReembolsoSandbox).filter_by(wompi_pago_id=attempt.id).first()):
        raise HTTPException(status_code=409, detail="Ya existe un reembolso o una solicitud para este pago.")
    pagos = db.query(Pago).filter_by(credito_id=attempt.credito_id, cuota_id=attempt.cuota_id, metodo_pago="WOMPI_SANDBOX").all()
    if len(pagos) != 1 or Decimal(str(pagos[0].monto_pagado)) != original_amount:
        raise HTTPException(status_code=409, detail="El pago interno cambió durante la validación.")
    if (txn.get("id") != attempt.wompi_transaction_id or txn.get("status") != "APPROVED"
            or txn.get("currency") != "COP" or txn.get("payment_link_id") != attempt.wompi_link_id
            or type(txn.get("amount_in_cents")) is not int or txn["amount_in_cents"] != int(centavos)):
        raise HTTPException(status_code=409, detail="Wompi no confirmó la transacción original.")
    s = SolicitudReembolsoSandbox(wompi_pago_id=attempt.id, pago_id=pagos[0].id,
        credito_id=attempt.credito_id, cuota_id=attempt.cuota_id, transaccion_id=attempt.wompi_transaction_id,
        monto_centavos=datos.monto_centavos, motivo=datos.motivo, descripcion=datos.descripcion,
        clasificacion=datos.clasificacion, evidencia=datos.evidencia, solicitante_id=user.id)
    db.add(s)
    try:
        db.flush()
        auditar(db, user, s, "SOLICITAR_REEMBOLSO_SANDBOX", {"monto_centavos": s.monto_centavos, "motivo": s.motivo, "clasificacion": s.clasificacion})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Ya existe una solicitud para el pago.") from exc
    db.refresh(s)
    return resumen(s)


@router.get("")
def listar(credito_id: int | None = None, pago_id: int | None = None, estado: str | None = None,
           db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    q = db.query(SolicitudReembolsoSandbox)
    if credito_id is not None:
        q = q.filter_by(credito_id=credito_id)
    if pago_id is not None:
        q = q.filter_by(pago_id=pago_id)
    if estado:
        q = q.filter_by(autorizacion=estado)
    return [resumen(s) for s in q.order_by(SolicitudReembolsoSandbox.id.desc()).limit(200)]


@router.get("/reservas/posiblemente-abandonadas")
def reservas_posiblemente_abandonadas(db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    """Diagnóstico conservador: no demuestra que la operación esté inactiva."""
    exigir_habilitado()
    try:
        minutos = int(os.getenv("WOMPI_REFUND_STALE_MINUTES", "30"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Umbral de revisión inválido.") from exc
    if not 1 <= minutos <= 10080:
        raise HTTPException(status_code=503, detail="Umbral de revisión fuera de rango.")
    limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    rows = (db.query(SolicitudReembolsoSandbox, WompiReembolsoSandbox)
            .join(WompiReembolsoSandbox, SolicitudReembolsoSandbox.reembolso_id == WompiReembolsoSandbox.id)
            .filter(SolicitudReembolsoSandbox.ejecucion == "CREANDO", WompiReembolsoSandbox.estado == "CREANDO",
                    WompiReembolsoSandbox.creado_en < limite)
            .order_by(WompiReembolsoSandbox.id).limit(100).all())
    return {"umbral_minutos": minutos, "operaciones": [
        {"solicitud_id": solicitud.id, "reembolso_id": refund.id, "referencia": refund.referencia,
         "creado_en": refund.creado_en, "estado": "CREANDO", "actividad_confirmada": None,
         "requiere_revision": True} for solicitud, refund in rows],
        "nota": "Antigüedad no confirma abandono; no se ha cambiado el estado ni se permite reenviar."}


@router.get("/{solicitud_id}")
def detalle(solicitud_id: int, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    s = obtener(db, solicitud_id)
    eventos = db.query(AuditLog).filter_by(entidad="solicitud_reembolso_sandbox", entidad_id=s.id).order_by(AuditLog.id).all()
    return {**resumen(s), "auditoria": [{"id": e.id, "usuario_id": e.usuario_id, "accion": e.accion,
                                        "fecha": e.fecha_creacion, "detalles": e.detalles} for e in eventos]}


@router.post("/{solicitud_id}/decision")
def decidir(solicitud_id: int, datos: Decision, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    s = obtener(db, solicitud_id, lock=True)
    if s.autorizacion != "PENDIENTE":
        raise HTTPException(status_code=409, detail="La solicitud ya fue decidida.")
    s.autorizacion, s.aprobador_id = datos.decision, user.id
    s.decidida_en, s.justificacion = datetime.now(timezone.utc), datos.justificacion
    if datos.decision == "APROBADA":
        s.version_aprobada = version(s)
    auditar(db, user, s, "DECIDIR_REEMBOLSO_SANDBOX", {"decision": s.autorizacion, "justificacion": datos.justificacion})
    db.commit()
    return resumen(s)


@router.post("/{solicitud_id}/revision-contable")
def revisar(solicitud_id: int, datos: RevisionContable, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    s = obtener(db, solicitud_id, lock=True)
    if s.cerrada_en:
        raise HTTPException(status_code=409, detail="La solicitud está cerrada.")
    s.revision_contable, s.observacion_contable = datos.resultado, datos.observacion
    auditar(db, user, s, "REVISAR_CLASIFICACION_SANDBOX", {"resultado": datos.resultado, "observacion": datos.observacion})
    db.commit()
    return resumen(s)


@router.post("/{solicitud_id}/ejecutar")
def ejecutar(solicitud_id: int, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    return ejecutar_autorizado(solicitud_id, "approved", db, user)


def ejecutar_autorizado(solicitud_id: int, escenario: str, db: Session, user: Usuario):
    """Coordina la operación entre procesos sin transacción durante la espera HTTP."""
    exigir_habilitado()
    engine = db.get_bind()
    if engine.dialect.name != "postgresql":
        # SQLite solo se utiliza en pruebas unitarias; recuperación requiere PostgreSQL.
        return _ejecutar_autorizado(solicitud_id, escenario, db, user)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as coordination:
        acquired = coordination.execute(text("SELECT pg_try_advisory_lock(:namespace, :ident)"),
                                        {"namespace": 112867, "ident": solicitud_id}).scalar_one()
        if not acquired:
            raise HTTPException(status_code=409, detail="Operación activa; requiere espera o revisión.")
        try:
            return _ejecutar_autorizado(solicitud_id, escenario, db, user)
        finally:
            try:
                coordination.execute(text("SELECT pg_advisory_unlock(:namespace, :ident)"),
                                     {"namespace": 112867, "ident": solicitud_id})
            except SQLAlchemyError:
                # A lost PostgreSQL session already releases its advisory lock;
                # do not mask the operation's conflict or uncertain result.
                logger.warning("Se perdió la conexión de coordinación del reembolso %s", solicitud_id)


def _ejecutar_autorizado(solicitud_id: int, escenario: str, db: Session, user: Usuario):
    """Único punto de reserva y envío; no mantiene una transacción durante HTTP."""
    exigir_habilitado()
    if user.rol != "ADMIN" or not user.activo or escenario not in {"approved", "declined", "error", "cancelled"}:
        raise HTTPException(status_code=403, detail="Operación no autorizada.")
    s = obtener(db, solicitud_id, lock=True)
    approver = db.get(Usuario, s.aprobador_id) if s.aprobador_id else None
    if (s.autorizacion != "APROBADA" or not approver or approver.rol != "ADMIN"
            or not s.decidida_en or not s.justificacion or not s.motivo or not s.clasificacion
            or s.version_aprobada != version(s) or s.ejecucion != "NO_ENVIADO" or s.reembolso_id):
        raise HTTPException(status_code=409, detail="Aprobación no válida o utilizada; requiere revisión.")
    pago = db.query(WompiPago).filter_by(id=s.wompi_pago_id).with_for_update().first()
    original = db.get(Pago, s.pago_id)
    if (not pago or pago.estado != "PAGADO" or pago.credito_id != s.credito_id or pago.cuota_id != s.cuota_id
            or pago.wompi_transaction_id != s.transaccion_id or not pago.wompi_link_id
            or not original or original.credito_id != s.credito_id or original.cuota_id != s.cuota_id
            or original.metodo_pago != "WOMPI_SANDBOX" or Decimal(str(original.monto_pagado)) != Decimal(str(pago.monto_esperado))
            or s.monto_centavos <= 0 or s.monto_centavos > int(Decimal(str(pago.monto_esperado)) * 100)
            or db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=pago.id).first()):
        raise HTTPException(status_code=409, detail="Pago o reserva incompatibles; requiere revisión.")
    expected, txid, linkid = int(Decimal(str(pago.monto_esperado)) * 100), s.transaccion_id, pago.wompi_link_id
    monto, referencia = s.monto_centavos, secrets.token_hex(16)
    refund = WompiReembolsoSandbox(wompi_pago_id=pago.id, referencia=referencia,
        monto=Decimal(monto) / 100, escenario=escenario, estado="CREANDO")
    db.add(refund)
    try:
        db.flush()
        refund_id = refund.id
        s.reembolso_id, s.ejecucion = refund_id, "CREANDO"
        auditar(db, user, s, "RESERVAR_REEMBOLSO_SANDBOX", {"reembolso_id": refund_id, "monto_centavos": monto})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="El pago ya tiene una reserva de reembolso.") from exc
    # Every subsequent failure remains reserved and requires investigation.
    estado, proveedor, provider_id = "INCIERTO", None, None
    try:
        txn = consultar_transaccion(txid)
        if (txn.get("id") != txid or txn.get("status") != "APPROVED" or txn.get("currency") != "COP"
                or txn.get("payment_link_id") != linkid or type(txn.get("amount_in_cents")) is not int
                or txn.get("amount_in_cents") != expected):
            raise ValueError("Transacción no confirmada")
        result = solicitar_reembolso_sandbox(transaction_id=txid, amount_in_cents=monto, reference=referencia, scenario=escenario)
        proveedor, provider_id = result["status"], result["refund_id"]
        estado = "CONFIRMADO" if proveedor == "APPROVED" else "NO_APROBADO"
    except Exception:
        pass
    s = obtener(db, solicitud_id, lock=True)
    refund = db.query(WompiReembolsoSandbox).filter_by(id=refund_id).with_for_update().first()
    if (not refund or s.reembolso_id != refund_id or s.ejecucion != "CREANDO" or refund.estado != "CREANDO"
            or refund.referencia != referencia or s.transaccion_id != txid or s.monto_centavos != monto
            or s.autorizacion != "APROBADA" or s.version_aprobada != version(s)
            or int(Decimal(str(refund.monto)) * 100) != monto):
        db.rollback()
        raise HTTPException(status_code=409, detail="Estado contradictorio; investigación manual requerida.")
    refund.estado, refund.estado_proveedor, refund.wompi_reembolso_id = estado, proveedor, provider_id
    s.ejecucion = estado
    auditar(db, user, s, "RESULTADO_REEMBOLSO_SANDBOX", {"reembolso_id": refund_id, "estado": estado})
    db.commit()
    return {**resumen(s), "estado_wompi": proveedor, "requiere_revision": True}


@router.post("/{solicitud_id}/recuperar")
def recuperar(solicitud_id: int, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    """Marca una reserva antigua como incierta; nunca autoriza un nuevo envío."""
    exigir_habilitado()
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(status_code=503, detail="La recuperación coordinada requiere PostgreSQL.")
    try:
        minutos = int(os.getenv("WOMPI_REFUND_STALE_MINUTES", "30"))
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Umbral inválido.") from exc
    if not 1 <= minutos <= 10080:
        raise HTTPException(status_code=503, detail="Umbral fuera de rango.")
    acquired = db.execute(text("SELECT pg_try_advisory_xact_lock(:namespace, :ident)"),
                          {"namespace": 112867, "ident": solicitud_id}).scalar_one()
    if not acquired:
        raise HTTPException(status_code=409, detail="Operación activa; no se recuperó.")
    s = obtener(db, solicitud_id, lock=True)
    if not s.reembolso_id:
        raise HTTPException(status_code=409, detail="No existe reserva para recuperar.")
    refund = db.query(WompiReembolsoSandbox).filter_by(id=s.reembolso_id).with_for_update().first()
    if not refund:
        raise HTTPException(status_code=409, detail="Reserva inconsistente; requiere revisión.")
    if s.ejecucion == "INCIERTO" and refund.estado == "INCIERTO":
        return {**resumen(s), "ya_recuperado": True}
    limite = datetime.now(timezone.utc) - timedelta(minutes=minutos)
    creado = refund.creado_en
    if creado.tzinfo is None:
        creado = creado.replace(tzinfo=timezone.utc)
    if s.ejecucion != "CREANDO" or refund.estado != "CREANDO" or creado > limite:
        raise HTTPException(status_code=409, detail="Reserva no es antigua o cambió de estado.")
    s.ejecucion, refund.estado = "INCIERTO", "INCIERTO"
    auditar(db, user, s, "RECUPERAR_RESERVA_REEMBOLSO_SANDBOX",
            {"reembolso_id": refund.id, "referencia": refund.referencia, "estado": "INCIERTO"})
    db.commit()
    return {**resumen(s), "ya_recuperado": False}


@router.post("/{solicitud_id}/verificar")
def verificar(solicitud_id: int, datos: ConsultaProveedor, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    s = obtener(db, solicitud_id)
    if not s.reembolso_id:
        raise HTTPException(status_code=409, detail="No hay una reserva para verificar.")
    refund = db.get(WompiReembolsoSandbox, s.reembolso_id)
    if not refund or refund.wompi_reembolso_id not in (None, datos.refund_id):
        raise HTTPException(status_code=409, detail="Identificador incompatible; requiere revisión manual.")
    rid, txid, monto = refund.id, s.transaccion_id, s.monto_centavos
    db.rollback()
    result = consultar_reembolso_sandbox(datos.refund_id)
    if (result.get("respuesta_http_wompi") != 200 or result.get("datos_confirmados") is not True
            or result.get("transaction_id") != txid or type(result.get("monto_centavos")) is not int
            or result.get("monto_centavos") != monto or result.get("estado") != "APPROVED"):
        s = obtener(db, solicitud_id, lock=True)
        if s.reembolso_id == rid and s.transaccion_id == txid and s.monto_centavos == monto:
            auditar(db, user, s, "ALERTA_VERIFICACION_REEMBOLSO_SANDBOX", {
                "reembolso_id": rid, "resultado": "DATOS_NO_CONFIRMADOS_O_CONTRADICTORIOS",
                "requiere_revision": True})
            db.commit()
        raise HTTPException(status_code=409, detail="Wompi no confirmó todos los datos; permanece en revisión.")
    s = obtener(db, solicitud_id, lock=True)
    refund = db.query(WompiReembolsoSandbox).filter_by(id=rid).with_for_update().first()
    if (not refund or s.reembolso_id != rid or s.transaccion_id != txid or s.monto_centavos != monto
            or refund.wompi_reembolso_id not in (None, datos.refund_id)
            or refund.estado not in ("INCIERTO", "CREANDO", "CONFIRMADO")):
        raise HTTPException(status_code=409, detail="Estado contradictorio; requiere revisión.")
    if s.verificacion == "CONFIRMADO":
        return {**resumen(s), "ya_verificado": True}
    refund.estado, refund.estado_proveedor, refund.wompi_reembolso_id = "CONFIRMADO", "APPROVED", datos.refund_id
    s.ejecucion, s.verificacion = "CONFIRMADO", "CONFIRMADO"
    auditar(db, user, s, "VERIFICAR_REEMBOLSO_SANDBOX", {"reembolso_id": rid, "estado": "APPROVED"})
    db.commit()
    return {**resumen(s), "ya_verificado": False}


@router.post("/{solicitud_id}/conciliacion-operativa")
def conciliar_operativamente(solicitud_id: int, datos: RevisionContable, db: Session = Depends(get_db), user: Usuario = Depends(ADMIN)):
    exigir_habilitado()
    s = obtener(db, solicitud_id, lock=True)
    if s.verificacion != "CONFIRMADO" or datos.resultado != "APROBADA":
        raise HTTPException(status_code=409, detail="Se requiere verificación y aprobación del cotejo de prueba.")
    if s.conciliacion == "COTEJADO_SANDBOX":
        return {**resumen(s), "ya_cotejado": True}
    s.conciliacion = "COTEJADO_SANDBOX"
    auditar(db, user, s, "COTEJAR_REEMBOLSO_SANDBOX", {"observacion": datos.observacion, "banco_real": False})
    db.commit()
    return {**resumen(s), "ya_cotejado": False}
