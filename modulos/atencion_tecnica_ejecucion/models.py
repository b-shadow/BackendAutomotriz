"""Modelos del modulo 3.5.3 Atencion Tecnica y Ejecucion del Servicio."""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    PlanServicioDetalle,
    PrioridadServicio,
    ServicioCatalogo,
)

class EstadoPresupuestoCita(models.TextChoices):
    """Estados del presupuesto de una cita."""
    BORRADOR = "BORRADOR", _("Borrador")
    COMUNICADO = "COMUNICADO", _("Comunicado")
    APROBADO = "APROBADO", _("Aprobado")
    RECHAZADO = "RECHAZADO", _("Rechazado")
    AJUSTADO = "AJUSTADO", _("Ajustado")
    CERRADO = "CERRADO", _("Cerrado")


class EstadoPresupuestoDetalle(models.TextChoices):
    """Estado de un servicio en el presupuesto."""
    ACTIVO = "ACTIVO", _("Activo")
    EXCLUIDO = "EXCLUIDO", _("Excluido")


class EstadoOrdenTrabajoGlobal(models.TextChoices):
    """Estados de la orden de trabajo global."""
    ABIERTA = "ABIERTA", _("Abierta")
    ASIGNADA = "ASIGNADA", _("Asignada")
    EN_PROCESO = "EN_PROCESO", _("En proceso")
    PAUSADA = "PAUSADA", _("Pausada")
    FINALIZADA = "FINALIZADA", _("Finalizada")
    CERRADA = "CERRADA", _("Cerrada")
    CANCELADA = "CANCELADA", _("Cancelada")

class EstadoOrdenTrabajoDetalle(models.TextChoices):
    """Estados de un servicio en la orden de trabajo."""
    POR_HACER = "POR_HACER", _("Por hacer")
    EN_PROCESO = "EN_PROCESO", _("En proceso")
    FINALIZADO = "FINALIZADO", _("Finalizado")
    INNECESARIO = "INNECESARIO", _("Innecesario")
    PAUSADO = "PAUSADO", _("Pausado")


class NivelCombustible(models.TextChoices):
    """Niveles de combustible en el tanque."""
    CUARTO = "1/4", _("1/4 de tanque")
    MITAD = "1/2", _("1/2 de tanque")
    TRES_CUARTOS = "3/4", _("3/4 de tanque")
    LLENO = "LLENO", _("Lleno")


class TipoAvanceVehiculo(models.TextChoices):
    """Tipo de avance reportado en una cita."""
    GENERAL = "GENERAL", _("General")
    SERVICIO = "SERVICIO", _("Servicio específico")

# ============================================================================
# Sección 4: Presupuesto
# ============================================================================

class PresupuestoCita(models.Model):
    """
    Presupuesto asociado a una cita.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="presupuestos_cita",
        verbose_name=_("empresa"),
    )
    cita = models.OneToOneField(
        Cita,
        on_delete=models.CASCADE,
        related_name="presupuesto",
        verbose_name=_("cita"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPresupuestoCita.choices,
        default=EstadoPresupuestoCita.BORRADOR,
        db_index=True,
    )
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    descuento = models.DecimalField(
        _("descuento"),
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
    comunicado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presupuestos_comunicados",
        verbose_name=_("comunicado por"),
    )
    comunicado_at = models.DateTimeField(
        _("comunicado en"),
        null=True,
        blank=True,
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
        db_table = "presupuestos_cita"
        ordering = ["-created_at"]
        verbose_name = _("Presupuesto Cita")
        verbose_name_plural = _("Presupuestos Cita")

    def __str__(self):
        return f"Presupuesto Cita {self.cita.id} - ${self.total}"


class PresupuestoDetalle(models.Model):
    """
    Detalle de servicios en el presupuesto.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="presupuestos_detalle",
        verbose_name=_("empresa"),
    )
    presupuesto = models.ForeignKey(
        PresupuestoCita,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("presupuesto"),
    )
    servicio_catalogo = models.ForeignKey(
        ServicioCatalogo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="presupuestos_detalles",
        verbose_name=_("servicio catálogo"),
    )
    descripcion = models.CharField(
        _("descripción"),
        max_length=255,
        help_text="Descripción del ítem (puede ser manual)"
    )
    cantidad = models.IntegerField(_("cantidad"), default=1)
    tiempo_estandar_min = models.IntegerField(
        _("tiempo estándar (minutos)"),
        default=0,
    )
    precio_unitario = models.DecimalField(
        _("precio unitario"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    subtotal = models.DecimalField(
        _("subtotal"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPresupuestoDetalle.choices,
        default=EstadoPresupuestoDetalle.ACTIVO,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "presupuestos_detalle"
        ordering = ["presupuesto", "-created_at"]
        verbose_name = _("Detalle Presupuesto")
        verbose_name_plural = _("Detalles Presupuesto")

    def __str__(self):
        return f"{self.descripcion} - ${self.subtotal}"


# ============================================================================
# Sección 6: Órdenes de Trabajo
# ============================================================================

class OrdenTrabajoGlobal(models.Model):
    """
    Orden de trabajo global asociada a una cita.
    Agrupa todos los servicios que se ejecutarán.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ordenes_trabajo_global",
        verbose_name=_("empresa"),
    )
    cita = models.OneToOneField(
        Cita,
        on_delete=models.CASCADE,
        related_name="orden_trabajo",
        verbose_name=_("cita"),
    )
    numero = models.CharField(
        _("número"),
        max_length=100,
        db_index=True,
        help_text="Número único de la orden"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoOrdenTrabajoGlobal.choices,
        default=EstadoOrdenTrabajoGlobal.ABIERTA,
        db_index=True,
    )
    asesor_responsable = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordenes_asignadas",
        verbose_name=_("asesor responsable"),
    )
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
    )
    fecha_apertura = models.DateTimeField(_("fecha de apertura"))
    fecha_cierre = models.DateTimeField(
        _("fecha de cierre"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "ordenes_trabajo_global"
        ordering = ["-fecha_apertura"]
        verbose_name = _("Orden de Trabajo Global")
        verbose_name_plural = _("Órdenes de Trabajo Global")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "numero"],
                name="unique_empresa_numero_orden"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "estado"]),
        ]

    def __str__(self):
        return f"OT {self.numero} ({self.estado})"


class OrdenTrabajoGlobalMecanico(models.Model):
    """
    Relación entre mecánicos y órdenes de trabajo.
    Un mecánico puede estar asignado a una orden.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ordenes_mecanicos",
        verbose_name=_("empresa"),
    )
    orden_global = models.ForeignKey(
        OrdenTrabajoGlobal,
        on_delete=models.CASCADE,
        related_name="mecanicos_asignados",
        verbose_name=_("orden de trabajo"),
    )
    mecanico = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="ordenes_trabajo",
        verbose_name=_("mecánico"),
    )
    es_principal = models.BooleanField(
        _("es principal"),
        default=False,
        help_text="Si hay un mecánico principal"
    )
    asignado_at = models.DateTimeField(_("asignado en"))
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "ordenes_trabajo_global_mecanicos"
        ordering = ["-asignado_at"]
        verbose_name = _("Mecánico Orden Trabajo")
        verbose_name_plural = _("Mecánicos Órdenes Trabajo")
        indexes = [
            models.Index(fields=["orden_global", "mecanico"]),
        ]

    def __str__(self):
        return f"{self.mecanico.nombres} - OT {self.orden_global.numero}"


class OrdenTrabajoDetalle(models.Model):
    """
    Detalle de cada servicio en la orden de trabajo.
    Un mecánico reporta el progreso aquí.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="ordenes_trabajo_detalle",
        verbose_name=_("empresa"),
    )
    orden_global = models.ForeignKey(
        OrdenTrabajoGlobal,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("orden de trabajo global"),
    )
    plan_detalle = models.ForeignKey(
        PlanServicioDetalle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordenes_detalles",
        verbose_name=_("detalle del plan"),
    )
    servicio_catalogo = models.ForeignKey(
        ServicioCatalogo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordenes_trabajo_detalles",
        verbose_name=_("servicio catálogo"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoOrdenTrabajoDetalle.choices,
        default=EstadoOrdenTrabajoDetalle.POR_HACER,
        db_index=True,
    )
    prioridad = models.CharField(
        _("prioridad"),
        max_length=20,
        choices=PrioridadServicio.choices,
        default=PrioridadServicio.MEDIA,
    )
    tiempo_estandar_min = models.IntegerField(
        _("tiempo estándar (minutos)"),
    )
    tiempo_real_min = models.IntegerField(
        _("tiempo real (minutos)"),
        null=True,
        blank=True,
    )
    mecanico_asignado = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="servicios_asignados",
        verbose_name=_("mecánico asignado"),
    )
    visible_cliente = models.BooleanField(
        _("visible para cliente"),
        default=True,
        help_text="Si el cliente puede verlo en su app"
    )
    observaciones_asesor = models.CharField(
        _("observaciones del asesor"),
        max_length=500,
        null=True,
        blank=True,
    )
    observaciones_mecanico = models.CharField(
        _("observaciones del mecánico"),
        max_length=500,
        null=True,
        blank=True,
    )
    inicio_real = models.DateTimeField(
        _("inicio real"),
        null=True,
        blank=True,
    )
    fin_real = models.DateTimeField(
        _("fin real"),
        null=True,
        blank=True,
    )
    precio_base = models.DecimalField(
        _("precio base"),
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    orden_visual = models.IntegerField(
        _("orden visual"),
        default=0,
        help_text="Orden en que aparece en la UI"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "ordenes_trabajo_detalle"
        ordering = ["orden_global", "orden_visual"]
        verbose_name = _("Detalle Orden Trabajo")
        verbose_name_plural = _("Detalles Órdenes Trabajo")
        indexes = [
            models.Index(fields=["orden_global", "estado"]),
            models.Index(fields=["mecanico_asignado"]),
        ]

    def __str__(self):
        return f"OT {self.orden_global.numero} - {self.servicio_catalogo.nombre if self.servicio_catalogo else 'N/A'}"


# ============================================================================
# Sección 6.5: Recepción del Vehículo
# ============================================================================

class RecepcionVehiculo(models.Model):
    """
    Registro de recepción de un vehículo para servicio.
    - Captura: Kilometraje, nivel de combustible, condición general
    - Cambia estado de cita de EN_ESPERA_INGRESO a EN_PROCESO
    - 1:1 con Cita (una recepción por cita)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="recepciones_vehiculo",
        verbose_name=_("empresa"),
    )
    cita = models.OneToOneField(
        Cita,
        on_delete=models.CASCADE,
        related_name="recepcion",
        verbose_name=_("cita"),
        help_text="Una recepción por cita"
    )
    asesor_registra = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recepciones_registradas",
        verbose_name=_("asesor que registra"),
    )
    fecha_recepcion = models.DateTimeField(
        _("fecha de recepción"),
        auto_now_add=True,
        help_text="Fecha/hora cuando se registra la recepción"
    )
    kilometraje_ingreso = models.IntegerField(
        _("kilometraje de ingreso"),
        help_text="Kilómetros del vehículo al ingresar"
    )
    nivel_combustible = models.CharField(
        _("nivel de combustible"),
        max_length=20,
        choices=NivelCombustible.choices,
        default=NivelCombustible.MITAD,
    )
    observaciones = models.TextField(
        _("observaciones adicionales"),
        blank=True,
        null=True,
        help_text="Notas adicionales sobre la recepción"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "recepciones_vehiculo"
        ordering = ["-fecha_recepcion"]
        verbose_name = _("Recepción Vehículo")
        verbose_name_plural = _("Recepciones Vehículos")
        indexes = [
            models.Index(fields=["empresa", "cita"]),
            models.Index(fields=["asesor_registra", "-fecha_recepcion"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "cita"],
                name="uq_recepcion_empresa_cita"
            )
        ]

    def __str__(self):
        return f"Recepción {self.cita.id} - {self.fecha_recepcion.strftime('%d/%m/%Y %H:%M')}"


# ============================================================================
# Sección 7: Avance del Vehículo
# ============================================================================

class AvanceVehiculo(models.Model):
    """
    Registro de avances/actualizaciones visibles para el cliente.
    Pueden ser avances generales o de un servicio específico.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="avances_vehiculo",
        verbose_name=_("empresa"),
    )
    cita = models.ForeignKey(
        Cita,
        on_delete=models.CASCADE,
        related_name="avances",
        verbose_name=_("cita"),
    )
    orden_detalle = models.ForeignKey(
        OrdenTrabajoDetalle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avances",
        verbose_name=_("detalle orden trabajo"),
        help_text="Si es avance de servicio específico"
    )
    registrado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="avances_registrados",
        verbose_name=_("registrado por"),
    )
    tipo = models.CharField(
        _("tipo"),
        max_length=20,
        choices=TipoAvanceVehiculo.choices,
    )
    estado_nuevo = models.CharField(
        _("estado nuevo"),
        max_length=100,
        help_text="Estado al que pasó (ej: En espera de piezas)"
    )
    mensaje = models.CharField(
        _("mensaje"),
        max_length=500,
        help_text="Mensaje a mostrar al cliente"
    )
    porcentaje_avance = models.IntegerField(
        _("porcentaje de avance"),
        null=True,
        blank=True,
        help_text="Porcentaje de avance (0-100)"
    )
    visible_cliente = models.BooleanField(
        _("visible para cliente"),
        default=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "avances_vehiculo"
        ordering = ["-created_at"]
        verbose_name = _("Avance Vehículo")
        verbose_name_plural = _("Avances Vehículo")
        indexes = [
            models.Index(fields=["cita", "-created_at"]),
        ]

    def __str__(self):
        return f"Avance {self.cita.id} - {self.estado_nuevo}"



