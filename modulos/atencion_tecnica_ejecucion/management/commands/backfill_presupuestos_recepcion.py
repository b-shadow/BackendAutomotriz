from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from modulos.atencion_tecnica_ejecucion.models import (
    PresupuestoCita,
    PresupuestoDetalle,
    EstadoPresupuestoCita,
    EstadoPresupuestoDetalle,
    RecepcionVehiculo,
)


class Command(BaseCommand):
    help = "Genera presupuestos faltantes para citas ya recepcionadas que aún no tienen presupuesto."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Aplica cambios. Sin este flag solo muestra conteo.")

    @transaction.atomic
    def handle(self, *args, **options):
        recepciones = (
            RecepcionVehiculo.objects.select_related("empresa", "cita")
            .prefetch_related("cita__detalles", "cita__detalles__servicio_catalogo")
            .all()
        )

        creados = 0
        omitidos = 0
        sin_detalles = 0

        for recepcion in recepciones:
            cita = recepcion.cita
            if PresupuestoCita.objects.filter(empresa=recepcion.empresa, cita=cita).exists():
                omitidos += 1
                continue

            detalles_cita = list(cita.detalles.all())
            if not detalles_cita:
                sin_detalles += 1
                continue

            if not options["apply"]:
                creados += 1
                continue

            presupuesto = PresupuestoCita.objects.create(
                empresa=recepcion.empresa,
                cita=cita,
                estado=EstadoPresupuestoCita.BORRADOR,
                subtotal=Decimal("0.00"),
                descuento=Decimal("0.00"),
                total=Decimal("0.00"),
                observaciones="Generado por backfill de recepcion.",
            )

            subtotal = Decimal("0.00")
            for cdet in detalles_cita:
                nombre = cdet.servicio_catalogo.nombre if cdet.servicio_catalogo else "Servicio"
                precio = cdet.precio_referencial or Decimal("0.00")
                PresupuestoDetalle.objects.create(
                    empresa=recepcion.empresa,
                    presupuesto=presupuesto,
                    servicio_catalogo=cdet.servicio_catalogo,
                    descripcion=nombre,
                    cantidad=1,
                    tiempo_estandar_min=cdet.tiempo_estandar_min or 0,
                    precio_unitario=precio,
                    subtotal=precio,
                    estado=EstadoPresupuestoDetalle.ACTIVO,
                )
                subtotal += precio

            presupuesto.subtotal = subtotal
            presupuesto.total = subtotal
            presupuesto.save(update_fields=["subtotal", "total", "updated_at"])
            creados += 1

        if options["apply"]:
            self.stdout.write(self.style.SUCCESS(f"Backfill completado. Presupuestos creados: {creados}"))
        else:
            self.stdout.write(self.style.WARNING(f"Dry-run: se crearían {creados} presupuestos."))
        self.stdout.write(f"Omitidos (ya tenían): {omitidos}")
        self.stdout.write(f"Recepciones sin detalles de cita: {sin_detalles}")
