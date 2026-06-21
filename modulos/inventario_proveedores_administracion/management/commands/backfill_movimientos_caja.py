from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.inventario_proveedores_administracion.models import (
    CajaUsuario,
    EstadoPagoTaller,
    MovimientoCaja,
    PagoTaller,
    TipoMovimientoCaja,
)


class Command(BaseCommand):
    help = (
        "Backfill de movimientos de caja (ingresos) desde pagos de taller "
        "confirmados/facturados/recibidos sin movimiento registrado."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant-slug",
            type=str,
            help="Slug del tenant a procesar. Si se omite, procesa todos.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula el backfill sin escribir cambios.",
        )
        parser.add_argument(
            "--actualizar-conceptos",
            action="store_true",
            help="Actualiza conceptos técnicos previos de backfill a formato legible.",
        )

    def _resolver_usuario_caja(self, empresa, pago):
        if pago.registrado_por and pago.registrado_por.empresa_id == empresa.id:
            return pago.registrado_por

        candidato = (
            Usuario.objects.filter(
                empresa=empresa,
                rol__nombre__in=["ADMIN", "ADMINISTRATIVO"],
                is_active=True,
            )
            .order_by("created_at")
            .first()
        )
        if candidato:
            return candidato

        return Usuario.objects.filter(empresa=empresa, is_active=True).order_by("created_at").first()

    def _obtener_o_crear_caja(self, empresa, usuario, dry_run=False):
        caja = CajaUsuario.objects.filter(
            empresa=empresa,
            administrativo=usuario,
            activa=True,
        ).first()
        if caja:
            return caja, False

        if dry_run:
            return None, True

        caja = CajaUsuario.objects.create(
            empresa=empresa,
            administrativo=usuario,
            nombre=f"Caja {usuario.nombres}",
            activa=True,
        )
        return caja, True

    def _nombre_cliente(self, pago):
        if pago.venta:
            if pago.venta.cliente_usuario:
                nom = f"{pago.venta.cliente_usuario.nombres} {pago.venta.cliente_usuario.apellidos or ''}".strip()
                return nom or "Cliente"
            return pago.venta.cliente_nombre_libre or "Cliente"

        if pago.cita and pago.cita.cliente:
            nom = f"{pago.cita.cliente.nombres} {pago.cita.cliente.apellidos or ''}".strip()
            return nom or "Cliente"

        return "Cliente"

    def _concepto_legible_ingreso(self, pago):
        cliente = self._nombre_cliente(pago)
        if pago.venta:
            return f"Ingreso venta mostrador - {cliente}"
        if pago.cita:
            return f"Ingreso pago cita - {cliente}"
        return f"Ingreso pago taller - {cliente}"

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant_slug")
        dry_run = options.get("dry_run", False)
        actualizar_conceptos = options.get("actualizar_conceptos", False)

        empresas_qs = Empresa.objects.all()
        if tenant_slug:
            empresas_qs = empresas_qs.filter(slug=tenant_slug)

        empresas = list(empresas_qs)
        if not empresas:
            raise CommandError("No se encontraron empresas para procesar.")

        self.stdout.write(self.style.WARNING(f"Modo dry-run: {dry_run}"))
        self.stdout.write(self.style.WARNING(f"Actualizar conceptos: {actualizar_conceptos}"))

        total_candidatos = 0
        total_creados = 0
        total_omitidos = 0
        total_cajas_creadas = 0
        total_conceptos_actualizados = 0

        for empresa in empresas:
            pagos_qs = (
                PagoTaller.objects.filter(
                    empresa=empresa,
                    estado__in=[
                        EstadoPagoTaller.CONFIRMADO,
                        EstadoPagoTaller.FACTURADO,
                        EstadoPagoTaller.RECIBIDO,
                    ],
                )
                .select_related("registrado_por", "venta__cliente_usuario", "cita__cliente")
                .order_by("created_at")
            )

            self.stdout.write(f"\nEmpresa: {empresa.nombre} ({empresa.slug})")
            empresa_creados = 0
            empresa_omitidos = 0
            empresa_candidatos = 0
            empresa_actualizados = 0

            for pago in pagos_qs:
                empresa_candidatos += 1
                mov_qs = MovimientoCaja.objects.filter(empresa=empresa, pago_taller=pago)

                if mov_qs.exists():
                    if actualizar_conceptos:
                        concepto_nuevo = self._concepto_legible_ingreso(pago)
                        for mov in mov_qs:
                            if (mov.concepto or "").startswith("Backfill ingreso pago"):
                                if dry_run:
                                    self.stdout.write(
                                        f"  - [DRY-RUN] Actualizaría concepto movimiento {mov.id} -> {concepto_nuevo}"
                                    )
                                else:
                                    mov.concepto = concepto_nuevo
                                    mov.save(update_fields=["concepto"])
                                empresa_actualizados += 1
                    empresa_omitidos += 1
                    continue

                usuario = self._resolver_usuario_caja(empresa, pago)
                if not usuario:
                    self.stdout.write(
                        self.style.WARNING(f"  - Pago {pago.id}: omitido (empresa sin usuarios activos).")
                    )
                    empresa_omitidos += 1
                    continue

                caja, creada = self._obtener_o_crear_caja(empresa, usuario, dry_run=dry_run)
                if creada:
                    total_cajas_creadas += 1
                    self.stdout.write(f"  - Caja activa creada para {usuario.email}")

                if dry_run:
                    self.stdout.write(f"  - [DRY-RUN] Crearía movimiento para pago {pago.id}")
                    empresa_creados += 1
                    continue

                concepto = self._concepto_legible_ingreso(pago)
                with transaction.atomic():
                    mov = MovimientoCaja.objects.create(
                        empresa=empresa,
                        caja=caja,
                        tipo=TipoMovimientoCaja.INGRESO,
                        concepto=concepto,
                        monto=pago.monto_pagado if pago.monto_pagado is not None else pago.monto_total,
                        pago_taller=pago,
                        venta=pago.venta,
                        registrado_por=usuario,
                    )
                    ts = pago.fecha_pago or pago.recibido_at or pago.updated_at or pago.created_at
                    MovimientoCaja.objects.filter(id=mov.id).update(created_at=ts)

                empresa_creados += 1

            total_candidatos += empresa_candidatos
            total_creados += empresa_creados
            total_omitidos += empresa_omitidos
            total_conceptos_actualizados += empresa_actualizados

            self.stdout.write(
                self.style.SUCCESS(
                    f"  Resumen empresa -> candidatos: {empresa_candidatos}, creados: {empresa_creados}, "
                    f"omitidos: {empresa_omitidos}, conceptos_actualizados: {empresa_actualizados}"
                )
            )

        self.stdout.write("\n=== Resumen Global ===")
        self.stdout.write(f"Empresas procesadas: {len(empresas)}")
        self.stdout.write(f"Pagos candidatos: {total_candidatos}")
        self.stdout.write(f"Movimientos creados: {total_creados}")
        self.stdout.write(f"Pagos omitidos: {total_omitidos}")
        self.stdout.write(f"Cajas creadas: {total_cajas_creadas}")
        self.stdout.write(f"Conceptos actualizados: {total_conceptos_actualizados}")
