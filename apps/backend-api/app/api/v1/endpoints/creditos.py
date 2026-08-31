import datetime
from decimal import Decimal
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.cliente import Cliente
from app.models.credito import Credito
from app.models.evaluacion import Evaluacion
from modules.creditos.motor_decision import evaluar_credito
from app.models.perfil_financiero import PerfilFinanciero
from app.core.deps import get_current_active_user, RoleChecker
from app.models.usuario import Usuario
from app.models.amortizacion import CuotaAmortizacion
from app.models.pago import Pago as PagoModel
from modules.creditos.amortizacion_service import generar_plan_amortizacion

from modules.audit.audit_service import registrar_auditoria
from modules.notificaciones.notification_service import crear_notificacion

router = APIRouter(
    prefix="/creditos",
    tags=["Créditos"]
)


def validar_transicion_estado(estado_actual: str, nuevo_estado: str):
    if estado_actual == nuevo_estado:
        return
    
    # Definir las transiciones permitidas explícitamente:
    # SOLICITADO -> APROBADO o RECHAZADO
    # APROBADO -> DESEMBOLSADO
    # DESEMBOLSADO -> PAGADO
    transiciones_permitidas = {
        "SOLICITADO": ["APROBADO", "RECHAZADO"],
        "APROBADO": ["DESEMBOLSADO"],
        "DESEMBOLSADO": ["PAGADO"],
        "RECHAZADO": [],
        "PAGADO": []
    }

    permitidos = transiciones_permitidas.get(estado_actual, [])
    if nuevo_estado not in permitidos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se permite transicionar el crédito de {estado_actual} a {nuevo_estado}."
        )


class PagoInputSchema(BaseModel):
    monto: Decimal = Field(gt=0, description="Monto a pagar")
    metodo_pago: str = Field(default="TRANSFERENCIA", description="Método de pago utilizado")


class DistribucionPago(BaseModel):
    cuota_id: int
    numero_cuota: int
    monto_aplicado: Decimal
    cuota_estado_resultante: str

    model_config = {"from_attributes": True}


class PagoResponse(BaseModel):
    mensaje: str
    monto_total_recibido: Decimal
    credito_estado: str
    distribucion_pagos: List[DistribucionPago]

    model_config = {"from_attributes": True}


class CuotaAmortizacionResponse(BaseModel):
    id: int
    credito_id: int
    numero_cuota: int
    fecha_vencimiento: datetime.datetime
    monto_cuota: Decimal
    capital: Decimal
    interes: Decimal
    saldo_remanente: Decimal
    monto_pagado: Decimal
    estado: str

    model_config = {"from_attributes": True}


class CreditoSchema(BaseModel):
    cliente_id: int = Field(gt=0)
    monto: float = Field(gt=0)
    plazo_meses: int = Field(gt=0)
    tasa_interes: float = Field(ge=0)


class EstadoCreditoSchema(BaseModel):
    estado: Literal["SOLICITADO", "APROBADO", "RECHAZADO", "DESEMBOLSADO", "PAGADO"]


class PagoHistoricoResponse(BaseModel):
    id: int
    credito_id: int
    cuota_id: int
    monto_pagado: Decimal
    fecha_pago: datetime.datetime
    metodo_pago: str

    model_config = {"from_attributes": True}


@router.get("/")
def listar_creditos(
    cliente_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado:
            raise HTTPException(
                status_code=403,
                detail="No tiene un perfil de cliente asociado"
            )
        if cliente_id is not None and cliente_id != cliente_asociado.id:
            raise HTTPException(
                status_code=403,
                detail="No autorizado para listar créditos de otro cliente"
            )
        cliente_id = cliente_asociado.id

    consulta = db.query(Credito)

    if cliente_id:
        consulta = consulta.filter(Credito.cliente_id == cliente_id)

    return consulta.all()


@router.get("/{credito_id}")
def obtener_credito(
    credito_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or credito.cliente_id != cliente_asociado.id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para ver este crédito"
            )

    return credito


@router.post("/", status_code=201)
def crear_credito(
    credito_data: CreditoSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or credito_data.cliente_id != cliente_asociado.id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para solicitar un crédito para este cliente"
            )

    cliente = (
        db.query(Cliente)
        .filter(Cliente.id == credito_data.cliente_id)
        .first()
    )

    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")

    # Validación preventiva de montos y plazos de microcréditos
    if credito_data.monto < 500000 or credito_data.monto > 1500000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto solicitado debe estar entre $500.000 y $1.500.000 COP"
        )
    if credito_data.plazo_meses > 12:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El plazo máximo es de 12 meses"
        )

    credito = Credito(
        cliente_id=credito_data.cliente_id,
        monto=credito_data.monto,
        plazo_meses=credito_data.plazo_meses,
        tasa_interes=credito_data.tasa_interes
    )

    db.add(credito)
    db.flush()

    if cliente.usuario_id:
        crear_notificacion(
            db=db,
            usuario_id=cliente.usuario_id,
            titulo="Solicitud de crédito recibida",
            mensaje=f"Su solicitud de crédito por ${float(credito.monto):,.2f} ha sido recibida exitosamente.",
            credito_id=credito.id
        )

    db.commit()
    db.refresh(credito)

    return {
        "mensaje": "Crédito creado correctamente",
        "credito": credito
    }


@router.patch("/{credito_id}/estado")
def actualizar_estado_credito(
    credito_id: int,
    estado_data: EstadoCreditoSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Los estados APROBADO ni RECHAZADO no pueden ser establecidos de forma manual
    if estado_data.estado in ["APROBADO", "RECHAZADO"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se permite establecer los estados APROBADO ni RECHAZADO manualmente. Esos estados solo pueden ser determinados por el motor de decisión a través del endpoint de evaluación."
        )

    # Los estados DESEMBOLSADO ni PAGADO tampoco pueden ser establecidos de forma manual
    if estado_data.estado in ["DESEMBOLSADO", "PAGADO"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se permite establecer el estado {estado_data.estado} manualmente. Este estado solo puede ser determinado por sus mecanismos específicos."
        )

    estado_anterior = credito.estado
    # Validación de máquina de estados para otras transiciones manuales
    validar_transicion_estado(credito.estado, estado_data.estado)

    credito.estado = estado_data.estado
    credito.fecha_evaluacion = datetime.datetime.now(datetime.timezone.utc)

    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="CAMBIAR_ESTADO_CREDITO",
        entidad="credito",
        entidad_id=credito.id,
        resultado="EXITOSO",
        detalles={
            "estado_anterior": estado_anterior,
            "estado_nuevo": credito.estado
        }
    )

    db.commit()
    db.refresh(credito)

    return {
        "mensaje": "Estado del crédito actualizado correctamente",
        "credito": credito
    }


@router.post("/{credito_id}/evaluar")
def evaluar_credito_endpoint(
    credito_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .first()
    )

    if not credito:
        raise HTTPException(
            status_code=404,
            detail="Crédito no encontrado"
        )

    # Validación preventiva de máquina de estados: evitar re-evaluar créditos ya finalizados
    if credito.estado in ["APROBADO", "RECHAZADO"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El crédito ya ha sido evaluado y se encuentra en estado terminal {credito.estado}."
        )

    perfil = (
        db.query(PerfilFinanciero)
        .filter(
            PerfilFinanciero.cliente_id == credito.cliente_id
        )
        .first()
    )

    if not perfil:
        raise HTTPException(
            status_code=404,
            detail="El cliente no tiene perfil financiero"
        )

    capacidad_mensual = (
        float(perfil.ingresos_mensuales)
        - float(perfil.gastos_mensuales)
        - float(perfil.otras_obligaciones)
    )

    resultado = evaluar_credito(
        monto=float(credito.monto),
        plazo_meses=credito.plazo_meses,
        capacidad_mensual=capacidad_mensual,
        tasa_interes_mensual=float(credito.tasa_interes)
    )

    # Actualizar estado y fecha de evaluación del crédito
    credito.estado = resultado.decision
    credito.fecha_evaluacion = datetime.datetime.now(datetime.timezone.utc)

    # Persistencia del resultado en el modelo Evaluacion
    evaluacion = Evaluacion(
        credito_id=credito.id,
        decision=resultado.decision,
        cuota_mensual=resultado.cuota_mensual,
        capacidad_mensual=capacidad_mensual,
        motivos=", ".join(resultado.motivos)
    )

    db.add(evaluacion)

    registrar_auditoria(
        db=db,
        usuario=current_user,
        accion="EVALUAR_CREDITO",
        entidad="credito",
        entidad_id=credito.id,
        resultado="EXITOSO",
        detalles={
            "decision": resultado.decision,
            "motivos": resultado.motivos,
            "cuota_mensual": str(resultado.cuota_mensual)
        }
    )

    cliente = db.query(Cliente).filter(Cliente.id == credito.cliente_id).first()
    if cliente and cliente.usuario_id:
        if resultado.decision == "APROBADO":
            crear_notificacion(
                db=db,
                usuario_id=cliente.usuario_id,
                titulo="Crédito aprobado",
                mensaje=f"Su solicitud de crédito por ${float(credito.monto):,.2f} ha sido aprobada.",
                credito_id=credito.id
            )
        elif resultado.decision == "RECHAZADO":
            crear_notificacion(
                db=db,
                usuario_id=cliente.usuario_id,
                titulo="Crédito rechazado",
                mensaje=f"Su solicitud de crédito por ${float(credito.monto):,.2f} ha sido rechazada.",
                credito_id=credito.id
            )

    db.commit()
    db.refresh(credito)

    return {
        "mensaje": "Crédito evaluado correctamente",
        "decision": resultado.decision,
        "motivos": resultado.motivos,
        "capacidad_mensual": capacidad_mensual,
        "cuota_mensual": resultado.cuota_mensual,
        "credito": credito
    }


@router.post("/{credito_id}/desembolsar")
def desembolsar_credito_endpoint(
    credito_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    # Bloqueo pesimista con with_for_update() para evitar condiciones de carrera concurrentes
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .with_for_update()
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Validar máquina de estados estrictamente
    if credito.estado == "DESEMBOLSADO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El crédito ya se encuentra en estado DESEMBOLSADO y no se puede desembolsar nuevamente."
        )

    if credito.estado != "APROBADO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se permite desembolsar un crédito en estado {credito.estado}. Debe estar en estado APROBADO."
        )

    # Comprobar preventivamente que no existan ya cuotas registradas para este crédito
    cuotas_existentes = (
        db.query(CuotaAmortizacion)
        .filter(CuotaAmortizacion.credito_id == credito.id)
        .first()
    )
    if cuotas_existentes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El crédito ya tiene un plan de amortización generado y no se puede desembolsar nuevamente."
        )

    # Obtener la evaluación persistida correspondiente al crédito
    evaluacion = (
        db.query(Evaluacion)
        .filter(Evaluacion.credito_id == credito.id)
        .first()
    )

    if not evaluacion:
        raise HTTPException(
            status_code=404,
            detail="No se encontró la evaluación correspondiente para este crédito."
        )

    # Generar el plan de amortización
    fecha_desembolso = datetime.datetime.now(datetime.timezone.utc)

    try:
        cuotas = generar_plan_amortizacion(
            credito=credito,
            evaluacion=evaluacion,
            fecha_desembolso=fecha_desembolso
        )

        # Operación atómica: actualización de estado y guardado de cuotas en la misma transacción
        credito.estado = "DESEMBOLSADO"
        for cuota in cuotas:
            db.add(cuota)

        registrar_auditoria(
            db=db,
            usuario=current_user,
            accion="DESEMBOLSAR_CREDITO",
            entidad="credito",
            entidad_id=credito.id,
            resultado="EXITOSO",
            detalles={
                "monto_desembolsado": str(credito.monto),
                "cuotas_generadas": len(cuotas)
            }
        )

        cliente = db.query(Cliente).filter(Cliente.id == credito.cliente_id).first()
        if cliente and cliente.usuario_id:
            crear_notificacion(
                db=db,
                usuario_id=cliente.usuario_id,
                titulo="Crédito desembolsado",
                mensaje=f"Su crédito por ${float(credito.monto):,.2f} ha sido desembolsado y se ha generado su plan de amortización.",
                credito_id=credito.id
            )

        db.commit()
        db.refresh(credito)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ocurrió un error interno al procesar el desembolso del crédito."
        )

    return {
        "mensaje": "Crédito desembolsado correctamente",
        "credito": credito,
        "cuotas_generadas": len(cuotas)
    }



@router.post("/{credito_id}/pagos", response_model=PagoResponse)
def registrar_pago_endpoint(
    credito_id: int,
    pago_data: PagoInputSchema,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(RoleChecker(["GESTOR", "ADMIN"]))
):
    # 1. Bloqueo pesimista del crédito para evitar condiciones de carrera en el estado principal
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .with_for_update()
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    if credito.estado != "DESEMBOLSADO":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pueden registrar pagos en un crédito con estado {credito.estado}. Debe estar DESEMBOLSADO."
        )

    # 2. Bloqueo pesimista de todas las cuotas de amortización asociadas para evitar concurrencia en la distribución
    cuotas = (
        db.query(CuotaAmortizacion)
        .filter(CuotaAmortizacion.credito_id == credito.id)
        .order_by(CuotaAmortizacion.numero_cuota.asc())
        .with_for_update()
        .all()
    )

    if not cuotas:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se encontró un plan de amortización para este crédito."
        )

    # Calcular la deuda total pendiente usando Decimal desde el inicio
    deuda_total = Decimal("0.00")
    for cuota in cuotas:
        saldo_pendiente_cuota = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
        deuda_total += saldo_pendiente_cuota

    monto_pago = pago_data.monto

    # Validar estrictamente que el pago no exceda la deuda total pendiente
    if monto_pago > deuda_total:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El monto del pago (${monto_pago}) excede la deuda pendiente total del crédito (${deuda_total})."
        )

    monto_remanente = monto_pago
    distribucion = []

    try:
        for cuota in cuotas:
            if monto_remanente <= Decimal("0.00"):
                break

            saldo_pendiente_cuota = Decimal(str(cuota.monto_cuota)) - Decimal(str(cuota.monto_pagado))
            if saldo_pendiente_cuota <= Decimal("0.00"):
                continue  # Cuota ya liquidada al 100%

            # Determinar el monto exacto a aplicar en este período
            monto_aplicado_cuota = min(monto_remanente, saldo_pendiente_cuota)
            
            # Sumar abono acumulativo a la cuota
            nuevo_pagado = Decimal(str(cuota.monto_pagado)) + monto_aplicado_cuota
            cuota.monto_pagado = nuevo_pagado

            # Transición del estado de la cuota según su saldo
            if nuevo_pagado >= Decimal(str(cuota.monto_cuota)):
                cuota.estado = "PAGADA"
            else:
                cuota.estado = "PAGO_PARCIAL"

            # Persistencia ineludible del Pago físico mapeado a su respectiva cuota
            pago_registro = PagoModel(
                credito_id=credito.id,
                cuota_id=cuota.id,
                monto_pagado=monto_aplicado_cuota,
                metodo_pago=pago_data.metodo_pago
            )
            db.add(pago_registro)

            distribucion.append({
                "cuota_id": cuota.id,
                "numero_cuota": cuota.numero_cuota,
                "monto_aplicado": monto_aplicado_cuota,
                "cuota_estado_resultante": cuota.estado
            })

            monto_remanente -= monto_aplicado_cuota

        registrar_auditoria(
            db=db,
            usuario=current_user,
            accion="REGISTRAR_PAGO",
            entidad="credito",
            entidad_id=credito.id,
            resultado="EXITOSO",
            detalles={
                "monto_pagado": str(monto_pago),
                "metodo_pago": pago_data.metodo_pago
            }
        )

        # Cierre automático de estado principal a "PAGADO" si todas están saldadas
        todas_pagadas = all(c.estado == "PAGADA" for c in cuotas)
        if todas_pagadas:
            credito.estado = "PAGADO"
            registrar_auditoria(
                db=db,
                usuario=current_user,
                accion="LIQUIDAR_CREDITO",
                entidad="credito",
                entidad_id=credito.id,
                resultado="EXITOSO",
                detalles={
                    "estado_nuevo": "PAGADO",
                    "mensaje": "El crédito ha sido totalmente pagado y liquidado."
                }
            )

        db.commit()
        db.refresh(credito)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ocurrió un error interno al registrar el pago del crédito."
        )

    return {
        "mensaje": "Pago procesado y aplicado correctamente",
        "monto_total_recibido": monto_pago,
        "credito_estado": credito.estado,
        "distribucion_pagos": distribucion
    }



@router.get("/{credito_id}/amortizacion", response_model=List[CuotaAmortizacionResponse])
def obtener_amortizacion_endpoint(
    credito_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Control estricto de seguridad IDOR para rol CLIENTE
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or credito.cliente_id != cliente_asociado.id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para ver la amortización de este crédito"
            )

    cuotas = (
        db.query(CuotaAmortizacion)
        .filter(CuotaAmortizacion.credito_id == credito.id)
        .order_by(CuotaAmortizacion.numero_cuota.asc())
        .all()
    )

    return cuotas


@router.get("/{credito_id}/pagos", response_model=List[PagoHistoricoResponse])
def obtener_pagos_endpoint(
    credito_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    credito = (
        db.query(Credito)
        .filter(Credito.id == credito_id)
        .first()
    )

    if not credito:
        raise HTTPException(status_code=404, detail="Crédito no encontrado")

    # Control estricto de seguridad IDOR para rol CLIENTE
    if current_user.rol == "CLIENTE":
        cliente_asociado = db.query(Cliente).filter(Cliente.usuario_id == current_user.id).first()
        if not cliente_asociado or credito.cliente_id != cliente_asociado.id:
            raise HTTPException(
                status_code=403,
                detail="No tiene permisos para ver los pagos de este crédito"
            )

    pagos = (
        db.query(PagoModel)
        .filter(PagoModel.credito_id == credito.id)
        .order_by(PagoModel.fecha_pago.desc())
        .all()
    )

    return pagos
