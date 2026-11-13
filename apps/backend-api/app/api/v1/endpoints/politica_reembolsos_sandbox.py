"""Etapas administrativas de reembolsos: sin movimientos de cartera ni envíos."""
import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.deps import RoleChecker
from app.models.audit_log import AuditLog
from app.models.pago import Pago
from app.models.solicitud_reembolso import SolicitudReembolsoSandbox
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.wompi_reembolso import WompiReembolsoSandbox
from app.services.wompi_service import consultar_transaccion, get_wompi_environment, verificar_configuracion_recaudo
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(prefix="/integraciones/wompi/sandbox/solicitudes-reembolso", tags=["Reembolsos Sandbox"])
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
            "pago_id": s.pago_id, "wompi_pago_id": s.wompi_pago_id,
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
    attempt = db.query(WompiPago).filter_by(id=datos.wompi_pago_id).with_for_update().first()
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
    txn = consultar_transaccion(attempt.wompi_transaction_id)
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
    exigir_habilitado()
    s = obtener(db, solicitud_id, lock=True)
    if s.autorizacion != "APROBADA" or s.version_aprobada != version(s):
        raise HTTPException(status_code=409, detail="Se requiere aprobación vigente y sin cambios.")
    # The legacy endpoint bypasses approval. Do not offer a new executor or
    # mark this policy complete until the caller explicitly resolves that conflict.
    raise HTTPException(status_code=409, detail="Ejecución deshabilitada: el endpoint anterior permite omitir la autorización. Requiere corrección y revisión.")
