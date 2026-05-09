from django.core.management.base import BaseCommand
from django.db import transaction

from modulos.atencion_tecnica_ejecucion.models import (
    AvanceVehiculo,
    TipoAvanceVehiculo,
    OrdenTrabajoGlobal,
    EstadoOrdenTrabajoGlobal,
    EstadoOrdenTrabajoDetalle,
)
from modulos.vehiculos_servicios_plan_citas.models import Cita, EstadoCita


class Command(BaseCommand):
    help = "Genera avances visibles faltantes para citas/OT ya existentes."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Aplica cambios; sin esto corre en dry-run.")
        parser.add_argument("--recompute", action="store_true", help="Recalcula también avances visibles ya existentes.")

    @transaction.atomic
    def handle(self, *args, **options):
        apply_changes = options["apply"]
        recompute = options["recompute"]

        creados = 0
        omitidos = 0

        # Candidatas: citas en proceso o con OT activa, sin avances visibles.
        citas_en_proceso = Cita.objects.filter(
            estado__in=[EstadoCita.EN_PROCESO]
        ).select_related("empresa")

        ot_activas = OrdenTrabajoGlobal.objects.filter(
            estado__in=[
                EstadoOrdenTrabajoGlobal.ABIERTA,
                EstadoOrdenTrabajoGlobal.ASIGNADA,
                EstadoOrdenTrabajoGlobal.EN_PROCESO,
                EstadoOrdenTrabajoGlobal.PAUSADA,
            ]
        ).select_related("empresa", "cita")

        candidatos = {c.id: c for c in citas_en_proceso}
        for ot in ot_activas:
            if ot.cita_id and ot.cita_id not in candidatos:
                candidatos[ot.cita_id] = ot.cita

        for cita in candidatos.values():
            existe_visible = AvanceVehiculo.objects.filter(
                empresa=cita.empresa,
                cita=cita,
                visible_cliente=True,
            ).exists()
            if existe_visible and not recompute:
                omitidos += 1
                continue

            orden = (
                OrdenTrabajoGlobal.objects.filter(cita=cita)
                .prefetch_related("detalles")
                .order_by("-created_at")
                .first()
            )
            porcentaje = 0
            estado = "EN TALLER"
            mensaje = "Vehiculo en proceso dentro del taller."
            if orden:
                total = orden.detalles.count()
                if total > 0:
                    resueltos = orden.detalles.filter(
                        estado__in=[EstadoOrdenTrabajoDetalle.FINALIZADO, EstadoOrdenTrabajoDetalle.INNECESARIO]
                    ).count()
                    porcentaje = int(round((resueltos * 100) / total))
                    if porcentaje >= 100:
                        estado = "FINALIZADO"
                        mensaje = "Todos los trabajos de la orden fueron resueltos."
                    elif resueltos > 0:
                        estado = "EN PROCESO"
                        mensaje = f"Avance {porcentaje}% ({resueltos}/{total} detalles resueltos)."

            if apply_changes:
                if existe_visible and recompute:
                    AvanceVehiculo.objects.filter(
                        empresa=cita.empresa,
                        cita=cita,
                        visible_cliente=True,
                    ).delete()
                AvanceVehiculo.objects.create(
                    empresa=cita.empresa,
                    cita=cita,
                    orden_detalle=None,
                    registrado_por=None,
                    tipo=TipoAvanceVehiculo.GENERAL,
                    estado_nuevo=estado,
                    mensaje=mensaje,
                    porcentaje_avance=porcentaje,
                    visible_cliente=True,
                )
            creados += 1

        if apply_changes:
            self.stdout.write(self.style.SUCCESS(f"Backfill aplicado. Avances creados: {creados}"))
        else:
            self.stdout.write(self.style.WARNING(f"Dry-run: se crearian {creados} avances."))
        self.stdout.write(f"Omitidos por ya tener avance visible: {omitidos}")
