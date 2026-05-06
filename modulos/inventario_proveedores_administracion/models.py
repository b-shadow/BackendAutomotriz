"""Modelos del modulo 3.5.4 Inventario, Proveedores y Gestion Administrativa."""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.atencion_tecnica_ejecucion.models import OrdenTrabajoGlobal
from modulos.vehiculos_servicios_plan_citas.models import Cita

RecepcionCompra = None
Recibo = None
CierreCaja = None
ArqueoCaja = None

class TipoItemInventario(models.TextChoices):
    """Tipos de items en inventario."""
    REPUESTO = "REPUESTO", _("Repuesto")
    INSUMO = "INSUMO", _("Insumo")
    PRODUCTO = "PRODUCTO", _("Producto")


class TipoMovimientoInventario(models.TextChoices):
    """Tipos de movimientos de inventario."""
    ENTRADA_COMPRA = "ENTRADA_COMPRA", _("Entrada por compra")
    SALIDA_TALLER = "SALIDA_TALLER", _("Salida al taller")
    SALIDA_VENTA = "SALIDA_VENTA", _("Salida por venta")
    AJUSTE = "AJUSTE", _("Ajuste")


class EstadoCompra(models.TextChoices):
    """Estados de una compra a proveedor."""
    BORRADOR = "BORRADOR", _("Borrador")
    CONFIRMADA = "CONFIRMADA", _("Confirmada")
    ANULADA = "ANULADA", _("Anulada")


class EstadoSolicitudRepuesto(models.TextChoices):
    """Estados de una solicitud de repuestos."""
    CREADA = "CREADA", _("Creada")
    APROBADA_POR_ASESOR = "APROBADA_POR_ASESOR", _("Aprobada por asesor")
    RECHAZADA_POR_ASESOR = "RECHAZADA_POR_ASESOR", _("Rechazada por asesor")
    EN_REVISION_ALMACEN = "EN_REVISION_ALMACEN", _("En revisión almacén")
    PARCIALMENTE_DISPONIBLE = "PARCIALMENTE_DISPONIBLE", _("Parcialmente disponible")
    ENTREGADA = "ENTREGADA", _("Entregada")
    CERRADA = "CERRADA", _("Cerrada")


class EstadoSolicitudRepuestoDetalle(models.TextChoices):
    """Estado de un item en una solicitud de repuestos."""
    SOLICITADO = "SOLICITADO", _("Solicitado")
    APROBADO = "APROBADO", _("Aprobado")
    PARCIAL = "PARCIAL", _("Parcial")
    ENTREGADO = "ENTREGADO", _("Entregado")
    SIN_STOCK = "SIN_STOCK", _("Sin stock")
    CANCELADO = "CANCELADO", _("Cancelado")


class EstadoVentaMostrador(models.TextChoices):
    """Estados de una venta en mostrador."""
    BORRADOR = "BORRADOR", _("Borrador")
    CONFIRMADA = "CONFIRMADA", _("Confirmada")
    ANULADA = "ANULADA", _("Anulada")


class TipoOrigenPagoTaller(models.TextChoices):
    """Origen del pago (qué lo generó)."""
    CITA = "CITA", _("Cita")
    VENTA = "VENTA", _("Venta")


class EstadoPagoTaller(models.TextChoices):
    """Estados de un pago de taller."""
    PENDIENTE = "PENDIENTE", _("Pendiente")
    REGISTRADO = "REGISTRADO", _("Registrado")
    RECIBIDO = "RECIBIDO", _("Recibido")
    FACTURADO = "FACTURADO", _("Facturado")
    ANULADO = "ANULADO", _("Anulado")


class TipoMovimientoCaja(models.TextChoices):
    """Tipos de movimientos en caja."""
    INGRESO = "INGRESO", _("Ingreso")
    EGRESO = "EGRESO", _("Egreso")
    AJUSTE = "AJUSTE", _("Ajuste")

# ============================================================================
# Sección 8: Inventario, Proveedores y Compras
# ============================================================================

class CategoriaInventario(models.Model):
    """
    Categorías de items de inventario (Repuestos, Insumos, Productos).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="categorias_inventario",
        verbose_name=_("empresa"),
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    descripcion = models.CharField(
        _("descripción"),
        max_length=500,
        null=True,
        blank=True,
    )
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "categorias_inventario"
        ordering = ["nombre"]
        verbose_name = _("Categoría Inventario")
        verbose_name_plural = _("Categorías Inventario")

    def __str__(self):
        return self.nombre


class ItemInventario(models.Model):
    """
    Items del inventario (repuestos, insumos, productos).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="items_inventario",
        verbose_name=_("empresa"),
    )
    categoria = models.ForeignKey(
        CategoriaInventario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
        verbose_name=_("categoría"),
    )
    codigo = models.CharField(
        _("código"),
        max_length=100,
        db_index=True,
        help_text="Código único del item"
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    descripcion = models.CharField(
        _("descripción"),
        max_length=500,
        null=True,
        blank=True,
    )
    tipo_item = models.CharField(
        _("tipo de item"),
        max_length=20,
        choices=TipoItemInventario.choices,
    )
    unidad_medida = models.CharField(
        _("unidad de medida"),
        max_length=50,
        help_text="Ej: pieza, litro, metro, etc"
    )
    stock_actual = models.IntegerField(
        _("stock actual"),
        default=0,
    )
    stock_minimo = models.IntegerField(
        _("stock mínimo"),
        default=0,
        help_text="Stock mínimo para alertas"
    )
    costo_promedio = models.DecimalField(
        _("costo promedio"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    precio_venta = models.DecimalField(
        _("precio venta"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "items_inventario"
        ordering = ["categoria", "nombre"]
        verbose_name = _("Item Inventario")
        verbose_name_plural = _("Items Inventario")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="unique_empresa_codigo_item"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "activo"]),
            models.Index(fields=["stock_actual"]),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class Proveedor(models.Model):
    """
    Proveedores de items de inventario.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="proveedores",
        verbose_name=_("empresa"),
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    telefono = models.CharField(
        _("teléfono"),
        max_length=20,
        null=True,
        blank=True,
    )
    email = models.EmailField(
        _("email"),
        null=True,
        blank=True,
    )
    direccion = models.CharField(
        _("dirección"),
        max_length=255,
        null=True,
        blank=True,
    )
    contacto = models.CharField(
        _("persona de contacto"),
        max_length=255,
        null=True,
        blank=True,
    )
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "proveedores"
        ordering = ["nombre"]
        verbose_name = _("Proveedor")
        verbose_name_plural = _("Proveedores")

    def __str__(self):
        return self.nombre


class Compra(models.Model):
    """
    Compras a proveedores.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="compras",
        verbose_name=_("empresa"),
    )
    proveedor = models.ForeignKey(
        Proveedor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compras",
        verbose_name=_("proveedor"),
    )
    numero_documento = models.CharField(
        _("número de documento"),
        max_length=100,
        help_text="Número de factura/documento del proveedor"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoCompra.choices,
        default=EstadoCompra.BORRADOR,
        db_index=True,
    )
    fecha_compra = models.DateField(_("fecha de compra"))
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    total = models.DecimalField(
        _("total"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compras_registradas",
        verbose_name=_("registrado por"),
    )
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "compras"
        ordering = ["-fecha_compra"]
        verbose_name = _("Compra")
        verbose_name_plural = _("Compras")

    def __str__(self):
        return f"Compra {self.numero_documento} - ${self.total}"


class CompraDetalle(models.Model):
    """
    Detalle de items en una compra.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="compras_detalle",
        verbose_name=_("empresa"),
    )
    compra = models.ForeignKey(
        Compra,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("compra"),
    )
    item_inventario = models.ForeignKey(
        ItemInventario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compras_detalles",
        verbose_name=_("item inventario"),
    )
    cantidad = models.IntegerField(_("cantidad"))
    costo_unitario = models.DecimalField(
        _("costo unitario"),
        max_digits=12,
        decimal_places=2,
    )
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "compras_detalle"
        ordering = ["compra"]
        verbose_name = _("Detalle Compra")
        verbose_name_plural = _("Detalles Compra")

    def __str__(self):
        return f"{self.item_inventario.nombre} x{self.cantidad}"


class MovimientoInventario(models.Model):
    """
    Movimientos de inventario (entradas, salidas, ajustes).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="movimientos_inventario",
        verbose_name=_("empresa"),
    )
    item_inventario = models.ForeignKey(
        ItemInventario,
        on_delete=models.CASCADE,
        related_name="movimientos",
        verbose_name=_("item inventario"),
    )
    tipo_movimiento = models.CharField(
        _("tipo de movimiento"),
        max_length=20,
        choices=TipoMovimientoInventario.choices,
        db_index=True,
    )
    cantidad = models.IntegerField(_("cantidad"), help_text="Cantidad positiva o negativa")
    stock_anterior = models.IntegerField(_("stock anterior"))
    stock_posterior = models.IntegerField(_("stock posterior"))
    referencia_tipo = models.CharField(
        _("referencia tipo"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Tipo de entidad que generó el movimiento (Compra, Cita, Venta)"
    )
    referencia_id = models.UUIDField(
        _("referencia ID"),
        null=True,
        blank=True,
        help_text="ID de la entidad que generó el movimiento"
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_registrados",
        verbose_name=_("registrado por"),
    )
    observacion = models.CharField(
        _("observación"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "movimientos_inventario"
        ordering = ["-created_at"]
        verbose_name = _("Movimiento Inventario")
        verbose_name_plural = _("Movimientos Inventario")
        indexes = [
            models.Index(fields=["item_inventario", "-created_at"]),
            models.Index(fields=["tipo_movimiento"]),
        ]

    def __str__(self):
        return f"{self.tipo_movimiento} - {self.item_inventario.nombre} ({self.cantidad})"

# ============================================================================
# Sección 9: Solicitudes de Repuestos
# ============================================================================

class SolicitudRepuesto(models.Model):
    """
    Solicitud de repuestos generada por mecánico/asesor para una cita.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="solicitudes_repuesto",
        verbose_name=_("empresa"),
    )
    cita = models.ForeignKey(
        Cita,
        on_delete=models.CASCADE,
        related_name="solicitudes_repuesto",
        verbose_name=_("cita"),
    )
    orden_global = models.ForeignKey(
        OrdenTrabajoGlobal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_repuesto",
        verbose_name=_("orden de trabajo"),
    )
    solicitado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_creadas",
        verbose_name=_("solicitado por"),
    )
    aprobado_por_asesor = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_aprobadas",
        verbose_name=_("aprobado por asesor"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=30,
        choices=EstadoSolicitudRepuesto.choices,
        default=EstadoSolicitudRepuesto.CREADA,
        db_index=True,
    )
    motivo = models.CharField(
        _("motivo"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Motivo de la solicitud"
    )
    observaciones_asesor = models.CharField(
        _("observaciones del asesor"),
        max_length=500,
        null=True,
        blank=True,
    )
    observaciones_almacen = models.CharField(
        _("observaciones del almacén"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "solicitudes_repuesto"
        ordering = ["-created_at"]
        verbose_name = _("Solicitud Repuesto")
        verbose_name_plural = _("Solicitudes Repuesto")
        indexes = [
            models.Index(fields=["cita", "estado"]),
        ]

    def __str__(self):
        return f"Solicitud Cita {self.cita.id} ({self.estado})"


class SolicitudRepuestoDetalle(models.Model):
    """
    Detalle de items en una solicitud de repuestos.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="solicitudes_repuesto_detalle",
        verbose_name=_("empresa"),
    )
    solicitud = models.ForeignKey(
        SolicitudRepuesto,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("solicitud"),
    )
    item_inventario = models.ForeignKey(
        ItemInventario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="solicitudes_detalles",
        verbose_name=_("item inventario"),
    )
    cantidad_solicitada = models.IntegerField(_("cantidad solicitada"))
    cantidad_aprobada = models.IntegerField(
        _("cantidad aprobada"),
        default=0,
    )
    cantidad_entregada = models.IntegerField(
        _("cantidad entregada"),
        default=0,
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoSolicitudRepuestoDetalle.choices,
        default=EstadoSolicitudRepuestoDetalle.SOLICITADO,
    )
    observacion = models.CharField(
        _("observación"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "solicitudes_repuesto_detalle"
        ordering = ["solicitud"]
        verbose_name = _("Detalle Solicitud Repuesto")
        verbose_name_plural = _("Detalles Solicitud Repuesto")

    def __str__(self):
        return f"{self.item_inventario.nombre} x{self.cantidad_solicitada}"


# ============================================================================
# Sección 10: Ventas, Pago de Taller, Factura y Caja
# ============================================================================

class VentaMostrador(models.Model):
    """
    Venta de productos/repuestos en mostrador.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ventas_mostrador",
        verbose_name=_("empresa"),
    )
    cliente_usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_mostrador",
        verbose_name=_("cliente usuario"),
        help_text="Si el cliente es usuario del sistema"
    )
    cliente_nombre_libre = models.CharField(
        _("nombre cliente (libre)"),
        max_length=255,
        null=True,
        blank=True,
        help_text="Si el cliente no es usuario"
    )
    cliente_documento = models.CharField(
        _("documento del cliente"),
        max_length=100,
        null=True,
        blank=True,
    )
    vendido_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_realizadas",
        verbose_name=_("vendido por"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoVentaMostrador.choices,
        default=EstadoVentaMostrador.BORRADOR,
        db_index=True,
    )
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    total = models.DecimalField(
        _("total"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "ventas_mostrador"
        ordering = ["-created_at"]
        verbose_name = _("Venta Mostrador")
        verbose_name_plural = _("Ventas Mostrador")
        indexes = [
            models.Index(fields=["estado", "-created_at"]),
        ]

    def __str__(self):
        cliente = self.cliente_usuario.nombres if self.cliente_usuario else self.cliente_nombre_libre
        return f"Venta {cliente} - ${self.total}"


class VentaMostradorDetalle(models.Model):
    """
    Detalle de items en una venta de mostrador.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ventas_mostrador_detalle",
        verbose_name=_("empresa"),
    )
    venta = models.ForeignKey(
        VentaMostrador,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("venta"),
    )
    item_inventario = models.ForeignKey(
        ItemInventario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ventas_detalles",
        verbose_name=_("item inventario"),
    )
    cantidad = models.IntegerField(_("cantidad"))
    precio_unitario = models.DecimalField(
        _("precio unitario"),
        max_digits=12,
        decimal_places=2,
    )
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "ventas_mostrador_detalle"
        ordering = ["venta"]
        verbose_name = _("Detalle Venta Mostrador")
        verbose_name_plural = _("Detalles Venta Mostrador")

    def __str__(self):
        return f"{self.item_inventario.nombre} x{self.cantidad}"


class PagoTaller(models.Model):
    """
    Pago generado por una cita o venta en el taller.
    Es diferente del Pago SaaS.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="pagos_taller",
        verbose_name=_("empresa"),
    )
    tipo_origen = models.CharField(
        _("tipo de origen"),
        max_length=20,
        choices=TipoOrigenPagoTaller.choices,
        help_text="Si es de una cita o venta"
    )
    cita = models.ForeignKey(
        Cita,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_taller",
        verbose_name=_("cita"),
    )
    venta = models.ForeignKey(
        VentaMostrador,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_taller",
        verbose_name=_("venta"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPagoTaller.choices,
        default=EstadoPagoTaller.PENDIENTE,
        db_index=True,
    )
    monto_total = models.DecimalField(
        _("monto total"),
        max_digits=12,
        decimal_places=2,
    )
    metodo_pago = models.CharField(
        _("método de pago"),
        max_length=50,
        help_text="Ej: Efectivo, Tarjeta, Transferencia"
    )
    moneda = models.CharField(
        _("moneda"),
        max_length=3,
        default="BOB",
    )
    referencia = models.CharField(
        _("referencia"),
        max_length=255,
        null=True,
        blank=True,
        help_text="Referencia del pago (número de transacción, etc)"
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_registrados",
        verbose_name=_("registrado por"),
    )
    recibido_at = models.DateTimeField(
        _("recibido en"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "pagos_taller"
        ordering = ["-created_at"]
        verbose_name = _("Pago Taller")
        verbose_name_plural = _("Pagos Taller")
        indexes = [
            models.Index(fields=["tipo_origen", "estado"]),
        ]

    def __str__(self):
        origen = f"Cita {self.cita.id}" if self.cita else f"Venta {self.venta.id}"
        return f"Pago {origen} - ${self.monto_total}"


class Factura(models.Model):
    """
    Factura emitida por un pago de taller.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="facturas",
        verbose_name=_("empresa"),
    )
    pago_taller = models.OneToOneField(
        PagoTaller,
        on_delete=models.CASCADE,
        related_name="factura",
        verbose_name=_("pago taller"),
    )
    numero = models.CharField(
        _("número"),
        max_length=100,
        db_index=True,
        help_text="Número único de la factura"
    )
    fecha_emision = models.DateTimeField(_("fecha de emisión"), auto_now_add=True)
    nit_razon_social = models.CharField(
        _("NIT/Razón social"),
        max_length=255,
        null=True,
        blank=True,
    )
    total = models.DecimalField(
        _("total"),
        max_digits=12,
        decimal_places=2,
    )
    html_generado = models.TextField(
        _("HTML generado"),
        null=True,
        blank=True,
        help_text="HTML de la factura"
    )
    archivo_pdf_url = models.CharField(
        _("URL archivo PDF"),
        max_length=500,
        null=True,
        blank=True,
        help_text="URL del PDF generado"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "facturas"
        ordering = ["-created_at"]
        verbose_name = _("Factura")
        verbose_name_plural = _("Facturas")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                name="unique_empresa_numero_factura"
            )
        ]

    def __str__(self):
        return f"Factura {self.numero}"


class CajaUsuario(models.Model):
    """
    Caja de cada usuario administrativo para movimientos de dinero.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="cajas_usuario",
        verbose_name=_("empresa"),
    )
    administrativo = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="cajas",
        verbose_name=_("usuario administrativo"),
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    activa = models.BooleanField(_("activa"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "cajas_usuario"
        ordering = ["nombre"]
        verbose_name = _("Caja Usuario")
        verbose_name_plural = _("Cajas Usuario")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "administrativo"],
                name="unique_empresa_administrativo_caja"
            )
        ]

    def __str__(self):
        return f"Caja {self.nombre} - {self.administrativo.nombres}"


class MovimientoCaja(models.Model):
    """
    Movimientos de caja (ingresos, egresos, ajustes).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="movimientos_caja",
        verbose_name=_("empresa"),
    )
    caja = models.ForeignKey(
        CajaUsuario,
        on_delete=models.CASCADE,
        related_name="movimientos",
        verbose_name=_("caja"),
    )
    tipo = models.CharField(
        _("tipo"),
        max_length=20,
        choices=TipoMovimientoCaja.choices,
        db_index=True,
    )
    concepto = models.CharField(
        _("concepto"),
        max_length=255,
        help_text="Descripción del movimiento"
    )
    monto = models.DecimalField(
        _("monto"),
        max_digits=12,
        decimal_places=2,
    )
    pago_taller = models.ForeignKey(
        PagoTaller,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_caja",
        verbose_name=_("pago taller"),
    )
    venta = models.ForeignKey(
        VentaMostrador,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_caja",
        verbose_name=_("venta"),
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movimientos_caja_registrados",
        verbose_name=_("registrado por"),
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "movimientos_caja"
        ordering = ["-created_at"]
        verbose_name = _("Movimiento Caja")
        verbose_name_plural = _("Movimientos Caja")
        indexes = [
            models.Index(fields=["caja", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.tipo} - ${self.monto}"


