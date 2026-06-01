from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.inventario_proveedores_administracion.models import (
    CajaUsuario,
    Compra,
    EstadoCompra,
    MovimientoCaja,
    TipoMovimientoCaja,
)


class Command(BaseCommand):
    help = (
        "Backfill de egresos de caja desde compras de insumos confirmadas "
        "que no tienen movimiento de egreso asociado."
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

    def _resolver_usuario(self, empresa, compra):
        if compra.registrado_por and compra.registrado_por.empresa_id == empresa.id:
            return compra.registrado_por
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

    def _concepto_compra(self, compra):
        obs = (compra.observaciones or "").strip()
        if obs:
            return obs
        proveedor = compra.proveedor.nombre if compra.proveedor else "Proveedor"
        numero = compra.numero_documento or str(compra.id)
        return f"Compra insumos {numero} - {proveedor}"

    def handle(self, *args, **options):
        tenant_slug = options.get("tenant_slug")
        dry_run = options.get("dry_run", False)

        empresas_qs = Empresa.objects.all()
        if tenant_slug:
            empresas_qs = empresas_qs.filter(slug=tenant_slug)
        empresas = list(empresas_qs)
        if not empresas:
            raise CommandError("No se encontraron empresas para procesar.")

        self.stdout.write(self.style.WARNING(f"Modo dry-run: {dry_run}"))
        total_candidatas = 0
        total_creadas = 0
        total_omitidas = 0
        total_cajas_creadas = 0

        for empresa in empresas:
            compras_qs = (
                Compra.objects.filter(empresa=empresa, estado=EstadoCompra.CONFIRMADA)
                .select_related("proveedor", "registrado_por")
                .order_by("created_at")
            )
            self.stdout.write(f"\nEmpresa: {empresa.nombre} ({empresa.slug})")
            empresa_candidatas = 0
            empresa_creadas = 0
            empresa_omitidas = 0

            for compra in compras_qs:
                empresa_candidatas += 1
                numero = compra.numero_documento or str(compra.id)

                # Dedupe razonable: si ya hay un egreso que contiene el nro documento, se omite.
                if MovimientoCaja.objects.filter(
                    empresa=empresa,
                    tipo=TipoMovimientoCaja.EGRESO,
                    concepto__icontains=numero,
                ).exists():
                    empresa_omitidas += 1
                    continue

                usuario = self._resolver_usuario(empresa, compra)
                if not usuario:
                    self.stdout.write(self.style.WARNING(f"  - Compra {compra.id}: omitida (sin usuarios activos)."))
                    empresa_omitidas += 1
                    continue

                caja, creada = self._obtener_o_crear_caja(empresa, usuario, dry_run=dry_run)
                if creada:
                    total_cajas_creadas += 1
                    self.stdout.write(f"  - Caja activa creada para {usuario.email}")

                concepto = self._concepto_compra(compra)

                if dry_run:
                    self.stdout.write(f"  - [DRY-RUN] Crearía egreso para compra {numero} -> {concepto}")
                    empresa_creadas += 1
                    continue

                with transaction.atomic():
                    mov = MovimientoCaja.objects.create(
                        empresa=empresa,
                        caja=caja,
                        tipo=TipoMovimientoCaja.EGRESO,
                        concepto=concepto,
                        monto=compra.total,
                        registrado_por=usuario,
                    )
                    ts = compra.updated_at or compra.created_at
                    MovimientoCaja.objects.filter(id=mov.id).update(created_at=ts)

                empresa_creadas += 1

            total_candidatas += empresa_candidatas
            total_creadas += empresa_creadas
            total_omitidas += empresa_omitidas
            self.stdout.write(
                self.style.SUCCESS(
                    f"  Resumen empresa -> candidatas: {empresa_candidatas}, creadas: {empresa_creadas}, omitidas: {empresa_omitidas}"
                )
            )

        self.stdout.write("\n=== Resumen Global ===")
        self.stdout.write(f"Empresas procesadas: {len(empresas)}")
        self.stdout.write(f"Compras candidatas: {total_candidatas}")
        self.stdout.write(f"Egresos creados: {total_creadas}")
        self.stdout.write(f"Compras omitidas: {total_omitidas}")
        self.stdout.write(f"Cajas creadas: {total_cajas_creadas}")
