from django.db import transaction
from django.utils import timezone

from modulos.atencion_tecnica_ejecucion.models import (
    OrdenTrabajoGlobal,
    OrdenTrabajoDetalle,
    EstadoPresupuestoCita,
    EstadoPresupuestoDetalle,
    EstadoOrdenTrabajoGlobal,
    EstadoOrdenTrabajoDetalle,
)


class OrdenTrabajoService:
    @staticmethod
    def generar_numero_orden(empresa):
        year = timezone.now().year
        base = f"OT-{year}"
        count = OrdenTrabajoGlobal.objects.filter(empresa=empresa, numero__startswith=base).count() + 1
        return f"{base}-{count:04d}"

    @staticmethod
    def servicios_autorizados_desde_fuente(cita):
        if hasattr(cita, "presupuesto"):
            presupuesto = cita.presupuesto
            if presupuesto.estado != EstadoPresupuestoCita.APROBADO:
                raise ValueError("El presupuesto existe pero no esta APROBADO.")
            detalles_pres = presupuesto.detalles.filter(estado=EstadoPresupuestoDetalle.ACTIVO).order_by("created_at")
            if not detalles_pres.exists():
                raise ValueError("El presupuesto aprobado no tiene servicios activos.")
            servicios = []
            for idx, pdet in enumerate(detalles_pres, start=1):
                servicios.append({
                    "plan_detalle_id": None,
                    "servicio_catalogo_id": str(pdet.servicio_catalogo_id) if pdet.servicio_catalogo_id else None,
                    "prioridad": "MEDIA",
                    "tiempo_estandar_min": int(pdet.tiempo_estandar_min or 0),
                    "precio_base": pdet.precio_unitario or 0,
                    "visible_cliente": True,
                    "observaciones_asesor": pdet.descripcion or "",
                    "orden_visual": idx,
                })
            return servicios

        cita_detalles = cita.detalles.all().order_by("orden_visual", "created_at")
        if not cita_detalles.exists():
            raise ValueError("La cita no tiene servicios autorizados para generar OT.")

        servicios = []
        for idx, cdet in enumerate(cita_detalles, start=1):
            prioridad = "MEDIA"
            if getattr(cdet, "plan_detalle", None) and getattr(cdet.plan_detalle, "prioridad", None):
                prioridad = cdet.plan_detalle.prioridad
            servicios.append({
                "plan_detalle_id": str(cdet.plan_detalle_id) if cdet.plan_detalle_id else None,
                "servicio_catalogo_id": str(cdet.servicio_catalogo_id) if cdet.servicio_catalogo_id else None,
                "prioridad": prioridad,
                "tiempo_estandar_min": int(cdet.tiempo_estandar_min or 0),
                "precio_base": cdet.precio_referencial or 0,
                "visible_cliente": True,
                "observaciones_asesor": cdet.observaciones or "",
                "orden_visual": idx,
            })
        return servicios

    @staticmethod
    @transaction.atomic
    def crear_orden_automatica(empresa, cita, asesor_responsable=None, observaciones=""):
        existente = OrdenTrabajoGlobal.objects.filter(
            empresa=empresa,
            cita=cita,
        ).exclude(estado__in=[EstadoOrdenTrabajoGlobal.CANCELADA, EstadoOrdenTrabajoGlobal.CERRADA]).first()
        if existente:
            return existente, False

        numero = OrdenTrabajoService.generar_numero_orden(empresa)
        orden = OrdenTrabajoGlobal.objects.create(
            empresa=empresa,
            cita=cita,
            numero=numero,
            estado=EstadoOrdenTrabajoGlobal.ABIERTA,
            asesor_responsable=asesor_responsable,
            observaciones=observaciones or "",
            fecha_apertura=timezone.now(),
        )

        detalles_payload = OrdenTrabajoService.servicios_autorizados_desde_fuente(cita)
        detalles_creados = 0
        for idx, det in enumerate(detalles_payload, start=1):
            tiempo_min = int(det.get("tiempo_estandar_min") or 0)
            if tiempo_min <= 0:
                continue
            OrdenTrabajoDetalle.objects.create(
                empresa=empresa,
                orden_global=orden,
                plan_detalle_id=det.get("plan_detalle_id"),
                servicio_catalogo_id=det.get("servicio_catalogo_id"),
                estado=EstadoOrdenTrabajoDetalle.POR_HACER,
                prioridad=det.get("prioridad", "MEDIA"),
                tiempo_estandar_min=tiempo_min,
                mecanico_asignado_id=det.get("mecanico_asignado_id"),
                visible_cliente=bool(det.get("visible_cliente", True)),
                observaciones_asesor=det.get("observaciones_asesor", ""),
                precio_base=det.get("precio_base", 0),
                orden_visual=int(det.get("orden_visual") or idx),
            )
            detalles_creados += 1

        if detalles_creados == 0:
            raise ValueError("No hay servicios validos para crear detalles de OT.")

        return orden, True
