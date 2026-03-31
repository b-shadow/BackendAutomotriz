"""
Servicio de Recepción Mínima - CU21

Centraliza la lógica de operaciones mínimas de recepción del vehículo:
- Registrar llegada del vehículo
- Ajustar servicios en recepción (antes de iniciar trabajo)
- Marcar cita como EN_PROCESO
- Marcar vehículo como devuelto/recolectado

NO usa modelos de recepción/inspección detallada.
Reutiliza validaciones de programación de citas.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from app.models import (
    Cita,
    CitaDetalle,
    CitaEspacioSegmento,
    Empresa,
    Usuario,
    PlanServicioVehiculo,
    PlanServicioDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
)
from app.services.citas_programacion_service import CitasProgramacionService
from app.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)


class CitasRecepcionService:
    """Servicio de lógica de recepción mínima de citas - CU21."""

    @staticmethod
    def registrar_llegada(
        cita: Cita,
        usuario: Usuario,
        empresa: Empresa,
        llegada_real_at: Optional[datetime] = None,
    ) -> Cita:
        """
        Registrar la llegada real del vehículo a la cita.

        Validaciones:
        - Cita debe estar en PROGRAMADA o EN_ESPERA_INGRESO
        - No se registra en canceladas, no-show, reprogramadas o finalizadas

        Lógica:
        - Si llegada_real_at no viene, usar timezone.now()
        - Si cita estaba PROGRAMADA, cambiar a EN_ESPERA_INGRESO
        - Si ya estaba EN_ESPERA_INGRESO, mantener estado
        - Guardar llegada_real_at
        - Registrar auditoría

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si la cita no es válida para esta operación
        """
        # Validación: estado válido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede registrar llegada en cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO son válidos."
            )

        # Asignar llegada si no viene
        if llegada_real_at is None:
            llegada_real_at = timezone.now()

        with transaction.atomic():
            # Actualizar cita
            cita.llegada_real_at = llegada_real_at
            
            # Cambiar estado si está PROGRAMADA
            if cita.estado == EstadoCita.PROGRAMADA:
                cita.estado = EstadoCita.EN_ESPERA_INGRESO
            
            cita.save()

            # Registrar auditoría
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Llegada registrada para cita {cita.id}",
                metadata={
                    "llegada_real_at": llegada_real_at.isoformat(),
                    "estado_anterior": cita.estado,
                    "estado_nuevo": cita.estado,
                },
            )

        return cita

    @staticmethod
    def ajustar_servicios_en_recepcion(
        cita: Cita,
        usuario: Usuario,
        empresa: Empresa,
        servicios_plan_detalle_ids: List[str],
        motivo_visita: Optional[str] = None,
        observaciones_cliente: Optional[str] = None,
    ) -> Cita:
        """
        Ajustar los servicios de una cita antes de iniciar trabajo.

        Validaciones:
        - Cita debe estar en PROGRAMADA o EN_ESPERA_INGRESO
        - No se permite si ya está EN_PROCESO o FINALIZADA
        - Todos los servicios deben pertenencer al plan de la cita
        - Validar que no estén en otra cita activa
        - Recalcular duración y segmentos

        Lógica:
        1. Validar plan y servicios
        2. Eliminar CitaDetalles anteriores y liberar sus PlanServicioDetalle
        3. Crear nuevos CitaDetalles para los servicios indicados
        4. Recalcular duración y segmentos (reutilizando lógica de programación)
        5. Actualizar motivo_visita y observaciones si vienen
        6. Registrar auditoría

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si hay problemas de validación
        """
        # Validación: estado válido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede ajustar servicios en cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO permiten ajustes."
            )

        # Validación: plan existe
        if not cita.plan_servicio:
            raise ValidationError("La cita no tiene un plan de servicio asociado.")

        # Obtener todos los servicios solicitados
        servicios = PlanServicioDetalle.objects.filter(
            id__in=servicios_plan_detalle_ids,
            plan_servicio=cita.plan_servicio,
        )

        if servicios.count() != len(servicios_plan_detalle_ids):
            raise ValidationError(
                "Algunos servicios no pertenecen al plan de la cita o no existen."
            )

        # Validar conflictos: que no estén en otra cita activa
        activas_estados = [
            EstadoCita.PROGRAMADA,
            EstadoCita.EN_ESPERA_INGRESO,
            EstadoCita.EN_PROCESO,
        ]
        conflictos = CitaDetalle.objects.filter(
            plan_detalle__in=servicios,
            cita__estado__in=activas_estados,
        ).exclude(cita=cita)

        if conflictos.exists():
            conflictos_ids = [str(cd.id) for cd in conflictos]
            raise ValidationError(
                f"Algunos servicios ya están en otras citas activas. IDs: {conflictos_ids}"
            )

        with transaction.atomic():
            # Guardar detalles anteriores para auditoría y segmentos anteriores
            detalles_antiguos = list(cita.detalles.all().values_list("plan_detalle_id", flat=True))
            segmentos_antiguos = list(cita.espacios_segmentos.all())

            # Obtener el espacio principal actual (primer segmento)
            primer_segmento = cita.espacios_segmentos.order_by("orden_segmento").first()
            if not primer_segmento:
                raise ValidationError(
                    "La cita no tiene segmentos de espacio para recalcular su programación."
                )

            # Calcular duración total con los nuevos servicios
            tiempo_total_min = 0
            for servicio_detalle in servicios:
                tiempo_total_min += servicio_detalle.tiempo_estandar_min

            # Preparar parámetros para recalcular la reserva canónica
            # Usamos el mismo inicio programado y espacio, con la nueva duración
            hora_inicio_min = (
                cita.fecha_hora_inicio_programada.hour * 60 +
                cita.fecha_hora_inicio_programada.minute
            )

            # Llamar al servicio de programación para validar que cabe
            resultado = CitasProgramacionService.construir_reserva_canonica(
                espacio_id=str(primer_segmento.espacio_trabajo.id),
                fecha_inicio=cita.fecha_hora_inicio_programada,
                hora_inicio_solicitada=hora_inicio_min,
                duracion_requerida_min=tiempo_total_min,
                empresa=empresa,
            )

            # Si no cabe, rechazar la operación (transacción se revierte)
            if not resultado.valido:
                raise ValidationError(
                    f"No se puede reprogramar la cita con la nueva combinación de servicios: {resultado.error}"
                )

            # Liberar detalles anteriores (vuelven a PENDIENTE)
            for cita_detalle in cita.detalles.all():
                if cita_detalle.plan_detalle:
                    cita_detalle.plan_detalle.estado = EstadoPlanServicioDetalle.PENDIENTE
                    cita_detalle.plan_detalle.save(update_fields=["estado", "updated_at"])
                cita_detalle.delete()

            # Crear nuevos CitaDetalles con los servicios seleccionados
            for idx, servicio_detalle in enumerate(servicios):
                CitaDetalle.objects.create(
                    empresa=empresa,
                    cita=cita,
                    plan_detalle=servicio_detalle,
                    servicio_catalogo=servicio_detalle.servicio_catalogo,
                    estado=EstadoPlanServicioDetalle.PROGRAMADO,
                    tiempo_estandar_min=servicio_detalle.tiempo_estandar_min,
                    precio_referencial=servicio_detalle.precio_referencial,
                    orden_visual=idx,
                )

                # Cambiar estado en el plan a PROGRAMADO
                servicio_detalle.estado = EstadoPlanServicioDetalle.PROGRAMADO
                servicio_detalle.save(update_fields=["estado", "updated_at"])

            # Eliminar segmentos antiguos
            for segmento_antiguo in segmentos_antiguos:
                segmento_antiguo.delete()

            # Crear nuevos segmentos desde el resultado canónico
            # resultado.segmentos es lista de diccionarios con "inicio_dt", "fin_dt", "duracion_min"
            for orden, segmento_info in enumerate(resultado.segmentos, 1):
                CitaEspacioSegmento.objects.create(
                    empresa=empresa,
                    cita=cita,
                    espacio_trabajo=primer_segmento.espacio_trabajo,
                    orden_segmento=orden,
                    tipo_segmento=getattr(primer_segmento, "tipo_segmento", "TALLER") or "TALLER",
                    inicio_programado=segmento_info["inicio_dt"],
                    fin_programado=segmento_info["fin_dt"],
                    motivo="Segmento recalculado por ajuste de servicios en recepción",
                )

            # Actualizar duración estimada y fecha fin programada
            cita.duracion_estimada_min = tiempo_total_min
            cita.fecha_hora_fin_programada = resultado.segmentos[-1]["fin_dt"] if resultado.segmentos else cita.fecha_hora_fin_programada

            # Actualizar motivo y observaciones si vienen
            if motivo_visita is not None:
                cita.motivo_visita = motivo_visita
            if observaciones_cliente is not None:
                cita.observaciones_cliente = observaciones_cliente

            cita.save()

            # Registrar auditoría
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Servicios ajustados en recepción de cita {cita.id}",
                metadata={
                    "servicios_recibidos": len(servicios),
                    "servicios_antiguos_ids": detalles_antiguos,
                    "servicios_nuevos_ids": [str(s.id) for s in servicios],
                    "duracion_estimada_min": tiempo_total_min,
                    "motivo_visita": motivo_visita,
                    "segmentos_recalculados": len(resultado.segmentos),
                },
            )

        return cita

    @staticmethod
    def marcar_en_proceso(
        cita: Cita,
        usuario: Usuario,
        empresa: Empresa,
        llegada_real_at: Optional[datetime] = None,
    ) -> Cita:
        """
        Marcar una cita como EN_PROCESO (inicio de trabajo).

        Validaciones:
        - Cita debe estar en PROGRAMADA o EN_ESPERA_INGRESO
        - No se marca si ya está EN_PROCESO, FINALIZADA, etc.

        Lógica:
        1. Si no existe llegada_real_at, guardarla
        2. Cambiar estado a EN_PROCESO
        3. NO tocar finalizada_at
        4. Registrar auditoría

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si la cita no es válida para esta operación
        """
        # Validación: estado válido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede marcar como EN_PROCESO una cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO son válidas."
            )

        with transaction.atomic():
            # Si no existe llegada_real_at, guardarla
            if not cita.llegada_real_at:
                cita.llegada_real_at = llegada_real_at or timezone.now()

            # Cambiar estado
            estado_anterior = cita.estado
            cita.estado = EstadoCita.EN_PROCESO
            cita.save()

            # Registrar auditoría
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Cita {cita.id} marcada como EN_PROCESO",
                metadata={
                    "estado_anterior": estado_anterior,
                    "estado_nuevo": cita.estado,
                    "llegada_real_at": cita.llegada_real_at.isoformat(),
                },
            )

        return cita

    @staticmethod
    def marcar_vehiculo_devuelto(
        cita: Cita,
        usuario: Usuario,
        empresa: Empresa,
        vehiculo_devuelto_at: Optional[datetime] = None,
    ) -> Cita:
        """
        Marcar el vehículo como devuelto/recolectado por el cliente.

        Validaciones:
        - Cita debe estar FINALIZADA o finalizada_at debe estar seteado
        - No se puede marcar dos veces

        Lógica:
        1. Validar que la cita está finalizada
        2. Si vehiculo_devuelto_at no viene, usar timezone.now()
        3. Si ya existe vehiculo_devuelto_at, error 400
        4. Guardar vehiculo_devuelto_at
        5. NO cambiar finalizada_at
        6. Registrar auditoría

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si hay problemas
        """
        # Validación: cita debe estar finalizada
        if not cita.finalizada_at:
            raise ValidationError(
                f"No se puede marcar vehículo devuelto en cita no finalizada. "
                f"Finaliza la cita primero (CU24)."
            )

        # Validación: no marcar dos veces
        if cita.vehiculo_devuelto_at:
            raise ValidationError(
                "El vehículo ya fue marcado como devuelto en esta cita."
            )

        # Asignar timestamp si no viene
        if vehiculo_devuelto_at is None:
            vehiculo_devuelto_at = timezone.now()

        with transaction.atomic():
            cita.vehiculo_devuelto_at = vehiculo_devuelto_at
            cita.save()

            # Registrar auditoría
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Vehículo marcado como devuelto en cita {cita.id}",
                metadata={
                    "vehiculo_devuelto_at": vehiculo_devuelto_at.isoformat(),
                },
            )

        return cita

    @staticmethod
    def construir_flags_acciones(cita: Cita) -> Dict[str, bool]:
        """
        Construir flags de qué acciones están permitidas en una cita.

        Retorna un diccionario con banderas booleanas:
        - puede_registrar_llegada: True si puede registrar llegada
        - puede_ajustar_servicios: True si puede ajustar servicios
        - puede_marcar_en_proceso: True si puede marcar EN_PROCESO
        - puede_marcar_vehiculo_devuelto: True si puede marcar vehículo devuelto
        """
        return {
            "puede_registrar_llegada": cita.estado in [
                EstadoCita.PROGRAMADA,
                EstadoCita.EN_ESPERA_INGRESO,
            ],
            "puede_ajustar_servicios": cita.estado in [
                EstadoCita.PROGRAMADA,
                EstadoCita.EN_ESPERA_INGRESO,
            ],
            "puede_marcar_en_proceso": cita.estado in [
                EstadoCita.PROGRAMADA,
                EstadoCita.EN_ESPERA_INGRESO,
            ],
            "puede_marcar_vehiculo_devuelto": bool(cita.finalizada_at) and not bool(cita.vehiculo_devuelto_at),
        }
