"""
Servicio de RecepciÃ³n MÃ­nima - CU21

Centraliza la lÃ³gica de operaciones mÃ­nimas de recepciÃ³n del vehÃ­culo:
- Registrar llegada del vehÃ­culo
- Ajustar servicios en recepciÃ³n (antes de iniciar trabajo)
- Marcar cita como EN_PROCESO
- Marcar vehÃ­culo como devuelto/recolectado

NO usa modelos de recepciÃ³n/inspecciÃ³n detallada.
Reutiliza validaciones de programaciÃ³n de citas.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    CitaDetalle,
    CitaEspacioSegmento,
    PlanServicioVehiculo,
    PlanServicioDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
)
from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)


class CitasRecepcionService:
    """Servicio de lÃ³gica de recepciÃ³n mÃ­nima de citas - CU21."""

    @staticmethod
    def registrar_llegada(
        cita: Cita,
        usuario: Usuario,
        empresa: Empresa,
        llegada_real_at: Optional[datetime] = None,
    ) -> Cita:
        """
        Registrar la llegada real del vehÃ­culo a la cita.

        Validaciones:
        - Cita debe estar en PROGRAMADA o EN_ESPERA_INGRESO
        - No se registra en canceladas, no-show, reprogramadas o finalizadas

        LÃ³gica:
        - Si llegada_real_at no viene, usar timezone.now()
        - Si cita estaba PROGRAMADA, cambiar a EN_ESPERA_INGRESO
        - Si ya estaba EN_ESPERA_INGRESO, mantener estado
        - Guardar llegada_real_at
        - Registrar auditorÃ­a

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si la cita no es vÃ¡lida para esta operaciÃ³n
        """
        # ValidaciÃ³n: estado vÃ¡lido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede registrar llegada en cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO son vÃ¡lidos."
            )

        # Asignar llegada si no viene
        if llegada_real_at is None:
            llegada_real_at = timezone.now()

        with transaction.atomic():
            # Actualizar cita
            cita.llegada_real_at = llegada_real_at
            
            # Cambiar estado si estÃ¡ PROGRAMADA
            if cita.estado == EstadoCita.PROGRAMADA:
                cita.estado = EstadoCita.EN_ESPERA_INGRESO
            
            cita.save()

            # Registrar auditorÃ­a
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
        - No se permite si ya estÃ¡ EN_PROCESO o FINALIZADA
        - Todos los servicios deben pertenencer al plan de la cita
        - Validar que no estÃ©n en otra cita activa
        - Recalcular duraciÃ³n y segmentos

        LÃ³gica:
        1. Validar plan y servicios
        2. Eliminar CitaDetalles anteriores y liberar sus PlanServicioDetalle
        3. Crear nuevos CitaDetalles para los servicios indicados
        4. Recalcular duraciÃ³n y segmentos (reutilizando lÃ³gica de programaciÃ³n)
        5. Actualizar motivo_visita y observaciones si vienen
        6. Registrar auditorÃ­a

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si hay problemas de validaciÃ³n
        """
        # ValidaciÃ³n: estado vÃ¡lido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede ajustar servicios en cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO permiten ajustes."
            )

        # ValidaciÃ³n: plan existe
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

        # Validar conflictos: que no estÃ©n en otra cita activa
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
                f"Algunos servicios ya estÃ¡n en otras citas activas. IDs: {conflictos_ids}"
            )

        with transaction.atomic():
            # Guardar detalles anteriores para auditorÃ­a y segmentos anteriores
            detalles_antiguos = list(cita.detalles.all().values_list("plan_detalle_id", flat=True))
            segmentos_antiguos = list(cita.espacios_segmentos.all())

            # Obtener el espacio principal actual (primer segmento)
            primer_segmento = cita.espacios_segmentos.order_by("orden_segmento").first()
            if not primer_segmento:
                raise ValidationError(
                    "La cita no tiene segmentos de espacio para recalcular su programaciÃ³n."
                )

            # Calcular duraciÃ³n total con los nuevos servicios
            tiempo_total_min = 0
            for servicio_detalle in servicios:
                tiempo_total_min += servicio_detalle.tiempo_estandar_min

            # Preparar parÃ¡metros para recalcular la reserva canÃ³nica
            # Usamos el mismo inicio programado y espacio, con la nueva duraciÃ³n
            hora_inicio_min = (
                cita.fecha_hora_inicio_programada.hour * 60 +
                cita.fecha_hora_inicio_programada.minute
            )

            # Llamar al servicio de programaciÃ³n para validar que cabe
            resultado = CitasProgramacionService.construir_reserva_canonica(
                espacio_id=str(primer_segmento.espacio_trabajo.id),
                fecha_inicio=cita.fecha_hora_inicio_programada,
                hora_inicio_solicitada=hora_inicio_min,
                duracion_requerida_min=tiempo_total_min,
                empresa=empresa,
            )

            # Si no cabe, rechazar la operaciÃ³n (transacciÃ³n se revierte)
            if not resultado.valido:
                raise ValidationError(
                    f"No se puede reprogramar la cita con la nueva combinaciÃ³n de servicios: {resultado.error}"
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

            # Crear nuevos segmentos desde el resultado canÃ³nico
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
                    motivo="Segmento recalculado por ajuste de servicios en recepciÃ³n",
                )

            # Actualizar duraciÃ³n estimada y fecha fin programada
            cita.duracion_estimada_min = tiempo_total_min
            cita.fecha_hora_fin_programada = resultado.segmentos[-1]["fin_dt"] if resultado.segmentos else cita.fecha_hora_fin_programada

            # Actualizar motivo y observaciones si vienen
            if motivo_visita is not None:
                cita.motivo_visita = motivo_visita
            if observaciones_cliente is not None:
                cita.observaciones_cliente = observaciones_cliente

            cita.save()

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Servicios ajustados en recepciÃ³n de cita {cita.id}",
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
        - No se marca si ya estÃ¡ EN_PROCESO, FINALIZADA, etc.

        LÃ³gica:
        1. Si no existe llegada_real_at, guardarla
        2. Cambiar estado a EN_PROCESO
        3. NO tocar finalizada_at
        4. Registrar auditorÃ­a

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si la cita no es vÃ¡lida para esta operaciÃ³n
        """
        # ValidaciÃ³n: estado vÃ¡lido
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise ValidationError(
                f"No se puede marcar como EN_PROCESO una cita con estado {cita.estado}. "
                f"Solo PROGRAMADA o EN_ESPERA_INGRESO son vÃ¡lidas."
            )

        with transaction.atomic():
            # Si no existe llegada_real_at, guardarla
            if not cita.llegada_real_at:
                cita.llegada_real_at = llegada_real_at or timezone.now()

            # Cambiar estado
            estado_anterior = cita.estado
            cita.estado = EstadoCita.EN_PROCESO
            cita.save()

            # Registrar auditorÃ­a
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
        Marcar el vehÃ­culo como devuelto/recolectado por el cliente.

        Validaciones:
        - Cita debe estar FINALIZADA o finalizada_at debe estar seteado
        - No se puede marcar dos veces

        LÃ³gica:
        1. Validar que la cita estÃ¡ finalizada
        2. Si vehiculo_devuelto_at no viene, usar timezone.now()
        3. Si ya existe vehiculo_devuelto_at, error 400
        4. Guardar vehiculo_devuelto_at
        5. NO cambiar finalizada_at
        6. Registrar auditorÃ­a

        Retorna:
        - Cita actualizada

        Excepciones:
        - ValidationError si hay problemas
        """
        # ValidaciÃ³n: cita debe estar finalizada
        if not cita.finalizada_at:
            raise ValidationError(
                f"No se puede marcar vehÃ­culo devuelto en cita no finalizada. "
                f"Finaliza la cita primero (CU24)."
            )

        # ValidaciÃ³n: no marcar dos veces
        if cita.vehiculo_devuelto_at:
            raise ValidationError(
                "El vehÃ­culo ya fue marcado como devuelto en esta cita."
            )

        # Asignar timestamp si no viene
        if vehiculo_devuelto_at is None:
            vehiculo_devuelto_at = timezone.now()

        with transaction.atomic():
            cita.vehiculo_devuelto_at = vehiculo_devuelto_at
            cita.save()

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=empresa,
                usuario=usuario,
                accion=AccionAuditoria.CITA_MODIFICADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"VehÃ­culo marcado como devuelto en cita {cita.id}",
                metadata={
                    "vehiculo_devuelto_at": vehiculo_devuelto_at.isoformat(),
                },
            )

        return cita

    @staticmethod
    def construir_flags_acciones(cita: Cita) -> Dict[str, bool]:
        """
        Construir flags de quÃ© acciones estÃ¡n permitidas en una cita.

        Retorna un diccionario con banderas booleanas:
        - puede_registrar_llegada: True si puede registrar llegada
        - puede_ajustar_servicios: True si puede ajustar servicios
        - puede_marcar_en_proceso: True si puede marcar EN_PROCESO
        - puede_marcar_vehiculo_devuelto: True si puede marcar vehÃ­culo devuelto
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

