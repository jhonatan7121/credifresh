"""Cotejo de informes sintéticos. No importa extractos reales ni mueve cartera."""

import hashlib
import json
from datetime import date
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.api.v1.endpoints.wompi import _exigir_sandbox_recaudo
from app.config.database import get_db
from app.core.deps import RoleChecker
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago
from app.models.usuario import Usuario
from app.models.wompi_pago import WompiPago
from app.models.wompi_reembolso import WompiReembolsoSandbox
from app.models.expediente_conciliacion import ExpedienteConciliacionSandbox, DiferenciaConciliacionSandbox
from app.services.wompi_service import consultar_transaccion
from modules.audit.audit_service import registrar_auditoria

router = APIRouter(prefix="/integraciones/wompi/sandbox", tags=["Conciliación Sandbox"])
MAX_CENTS = 99_999_999_999_999


class TransaccionInforme(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transaction_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    monto_centavos: int = Field(gt=0, le=MAX_CENTS, strict=True)


class InformeSandbox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    periodo_desde: date
    periodo_hasta: date
    referencia_abono_wompi: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    transacciones: list[TransaccionInforme] = Field(min_length=1, max_length=20)
    comisiones_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)
    impuestos_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)
    reembolsos_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)
    otros_descuentos_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)
    neto_informe_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)
    referencia_abono_banco: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    abono_banco_centavos: int = Field(ge=0, le=MAX_CENTS, strict=True)

    @model_validator(mode="after")
    def validar_informe(self):
        if self.periodo_desde > self.periodo_hasta:
            raise ValueError("El inicio del periodo no puede ser posterior al final.")
        ids = [t.transaction_id for t in self.transacciones]
        if len(ids) != len(set(ids)):
            raise ValueError("El informe contiene transacciones duplicadas.")
        return self


def _comparar_informe(informe, db, current_user, *, commit):
    """Cotejar cifras ingresadas, sin afirmar autenticidad o completitud del extracto."""
    _exigir_sandbox_recaudo()
    warnings = []
    total = 0
    for item in informe.transacciones:
        total += item.monto_centavos
        attempt = db.query(WompiPago).filter_by(wompi_transaction_id=item.transaction_id).first()
        if not attempt:
            warnings.append({"transaction_id": item.transaction_id, "motivo": "NO_REGISTRADA_EN_CARTERA"})
            continue
        remote = consultar_transaccion(item.transaction_id)
        payments = db.query(Pago).filter_by(credito_id=attempt.credito_id, cuota_id=attempt.cuota_id,
                                           metodo_pago="WOMPI_SANDBOX").all()
        quota = db.query(CuotaAmortizacion).filter_by(id=attempt.cuota_id, credito_id=attempt.credito_id).first()
        local_cents = int((Decimal(str(attempt.monto_esperado)) * 100).quantize(Decimal("1")))
        if (attempt.estado != "PAGADO" or remote.get("status") != "APPROVED"
                or remote.get("currency") != "COP" or type(remote.get("amount_in_cents")) is not int
                or remote.get("amount_in_cents") != item.monto_centavos or local_cents != item.monto_centavos
                or remote.get("payment_link_id") != attempt.wompi_link_id
                or len(payments) != 1 or Decimal(str(payments[0].monto_pagado)) * 100 != item.monto_centavos
                or not quota or quota.estado != "PAGADA"
                or Decimal(str(quota.monto_cuota)) * 100 != item.monto_centavos
                or Decimal(str(quota.monto_pagado)) * 100 != item.monto_centavos):
            warnings.append({"transaction_id": item.transaction_id, "motivo": "DIFERENCIA_TRANSACCION_O_CARTERA"})
        if db.query(WompiReembolsoSandbox).filter_by(wompi_pago_id=attempt.id).first():
            warnings.append({"transaction_id": item.transaction_id, "motivo": "REEMBOLSO_REQUIERE_REVISION"})
    expected = (total - informe.comisiones_centavos - informe.impuestos_centavos
                - informe.reembolsos_centavos - informe.otros_descuentos_centavos)
    if expected < 0:
        warnings.append({"motivo": "DESCUENTOS_SUPERAN_RECAUDO"})
    if expected != informe.neto_informe_centavos:
        warnings.append({"motivo": "NETO_WOMPI_NO_COINCIDE"})
    if informe.referencia_abono_wompi != informe.referencia_abono_banco:
        warnings.append({"motivo": "REFERENCIAS_ABONO_NO_COINCIDEN"})
    if informe.abono_banco_centavos != informe.neto_informe_centavos:
        warnings.append({"motivo": "MONTO_ABONO_NO_COINCIDE"})
    if informe.reembolsos_centavos:
        warnings.append({"motivo": "REEMBOLSOS_DEL_INFORME_REQUIEREN_REVISION"})
    digest = hashlib.sha256(informe.model_dump_json().encode("utf-8")).hexdigest()
    result = {"ambiente": "sandbox", "moneda": "COP", "origen_informes": "INGRESADOS_MANUALMENTE",
              "informes_autenticados_o_completitud_verificada": False, "cotejo_sin_diferencias": not warnings,
              "resultado": "REQUIERE_REVISION", "recaudo_bruto_centavos": total,
              "neto_calculado_centavos": expected, "neto_informe_centavos": informe.neto_informe_centavos,
              "abono_banco_centavos": informe.abono_banco_centavos, "diferencias": warnings,
              "huella_informe_sha256": digest}
    registrar_auditoria(db=db, usuario=current_user, accion="COTEJAR_INFORME_WOMPI_SANDBOX",
        entidad="conciliacion", entidad_id=None, resultado="REQUIERE_REVISION",
        detalles={"huella_informe_sha256": digest, "total_centavos": total,
                  "neto_calculado_centavos": expected, "diferencias": len(warnings)})
    if commit:
        db.commit()
    return result


@router.post("/conciliacion-informe")
def comparar_informe_sandbox(informe: InformeSandbox, db: Session = Depends(get_db),
        current_user: Usuario = Depends(RoleChecker(["ADMIN"]))):
    return _comparar_informe(informe, db, current_user, commit=True)


class RevisionDiferencia(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    observacion: str = Field(min_length=10, max_length=2000)


class NuevaEvaluacion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clave: str = Field(pattern=r"^[a-f0-9]{32}$")


def _expediente_resultado(db, expediente):
    diferencias = db.query(DiferenciaConciliacionSandbox).filter_by(expediente_id=expediente.id).order_by(DiferenciaConciliacionSandbox.indice).all()
    return {"id": expediente.id, "origen_id": expediente.origen_id, "huella": expediente.huella, "estado": expediente.estado,
        "creador_id": expediente.creador_id, "creada_en": expediente.creada_en,
        "ambiente": "sandbox", "conciliacion_bancaria_real": False,
        "informe": json.loads(expediente.informe_json), "resultado": json.loads(expediente.resultado_json),
        "diferencias": [{"id": d.id, "motivo": d.motivo, "transaction_id": d.transaccion_id,
            "estado": d.estado, "observacion": d.observacion, "revisor_id": d.revisor_id,
            "revisada_en": d.revisada_en} for d in diferencias]}


@router.post("/expedientes-conciliacion")
def crear_expediente(informe: InformeSandbox, db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))):
    _exigir_sandbox_recaudo()
    digest = hashlib.sha256(informe.model_dump_json().encode("utf-8")).hexdigest()
    return _guardar_expediente(informe, db, current_user, digest, None)


def _guardar_expediente(informe, db, current_user, digest, origen_id):
    anterior = db.query(ExpedienteConciliacionSandbox).filter_by(huella=digest).first()
    if anterior:
        return {**_expediente_resultado(db, anterior), "ya_existia": True}
    resultado = _comparar_informe(informe, db, current_user, commit=False)
    expediente = ExpedienteConciliacionSandbox(huella=digest, informe_json=informe.model_dump_json(),
        resultado_json=json.dumps(resultado, ensure_ascii=False), creador_id=current_user.id, estado="REQUIERE_REVISION", origen_id=origen_id)
    db.add(expediente)
    try:
        db.flush()
        for indice, diferencia in enumerate(resultado["diferencias"]):
            db.add(DiferenciaConciliacionSandbox(expediente_id=expediente.id, indice=indice,
                motivo=diferencia["motivo"], transaccion_id=diferencia.get("transaction_id"), estado="ABIERTA"))
        registrar_auditoria(db=db, usuario=current_user, accion="CREAR_EXPEDIENTE_CONCILIACION_SANDBOX",
            entidad="conciliacion", entidad_id=expediente.id, resultado="REQUIERE_REVISION", detalles={"huella": digest})
        db.commit()
    except IntegrityError:
        db.rollback()
        anterior = db.query(ExpedienteConciliacionSandbox).filter_by(huella=digest).first()
        if not anterior:
            raise
        return {**_expediente_resultado(db, anterior), "ya_existia": True}
    return {**_expediente_resultado(db, expediente), "ya_existia": False}


@router.post("/expedientes-conciliacion/{expediente_id}/reevaluar")
def reevaluar_expediente(expediente_id: int, datos: NuevaEvaluacion, db: Session = Depends(get_db),
        current_user: Usuario = Depends(RoleChecker(["ADMIN"]))):
    _exigir_sandbox_recaudo()
    origen = db.get(ExpedienteConciliacionSandbox, expediente_id)
    if not origen:
        raise HTTPException(status_code=404, detail="Expediente no encontrado")
    informe = InformeSandbox.model_validate_json(origen.informe_json)
    digest = hashlib.sha256(f"reevaluacion:{expediente_id}:{datos.clave}".encode()).hexdigest()
    return _guardar_expediente(informe, db, current_user, digest, expediente_id)


@router.get("/expedientes-conciliacion")
def listar_expedientes(db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))):
    _exigir_sandbox_recaudo()
    return [_expediente_resultado(db, item) for item in db.query(ExpedienteConciliacionSandbox).order_by(ExpedienteConciliacionSandbox.id.desc()).limit(100)]


@router.post("/expedientes-conciliacion/{expediente_id}/diferencias/{diferencia_id}/revision")
def revisar_diferencia(expediente_id: int, diferencia_id: int, datos: RevisionDiferencia,
        db: Session = Depends(get_db), current_user: Usuario = Depends(RoleChecker(["ADMIN"]))):
    _exigir_sandbox_recaudo()
    diferencia = db.query(DiferenciaConciliacionSandbox).filter_by(id=diferencia_id, expediente_id=expediente_id).with_for_update().first()
    if not diferencia:
        raise HTTPException(status_code=404, detail="Diferencia no encontrada")
    if diferencia.estado != "ABIERTA":
        raise HTTPException(status_code=409, detail="La diferencia ya fue revisada")
    diferencia.estado = "REVISADA"
    diferencia.observacion = datos.observacion
    diferencia.revisor_id = current_user.id
    diferencia.revisada_en = datetime.now(timezone.utc)
    registrar_auditoria(db=db, usuario=current_user, accion="REVISAR_DIFERENCIA_CONCILIACION_SANDBOX",
        entidad="conciliacion", entidad_id=expediente_id, resultado="REQUIERE_REVISION",
        detalles={"diferencia_id": diferencia_id, "observacion": datos.observacion})
    db.commit()
    return _expediente_resultado(db, db.get(ExpedienteConciliacionSandbox, expediente_id))
