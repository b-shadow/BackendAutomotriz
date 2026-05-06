"""Modelos del modulo 3.5.2 Vehiculos, Servicios, Plan y Citas."""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario

AgendaTaller = None
NoShowRegistro = None

# ============================================================================
# ENUMS / CHOICES - TALLER AUTOMOTRIZ
# ============================================================================

class EstadoVehiculo(models.TextChoices):
    """Estados de un vehículo."""
    ACTIVO = "ACTIVO", _("Activo")
    INACTIVO = "INACTIVO", _("Inactivo")


class EstadoPlanServicioVehiculo(models.TextChoices):
    """Estados del plan general de servicios de un vehículo.
    
    LIBRE: El plan existe pero no está siendo usado en ninguna cita activa.
    EN_EJECUCION: El plan está siendo usado en una o más citas activas.
    """
    LIBRE = "LIBRE", _("Libre")
    EN_EJECUCION = "EN_EJECUCION", _("En ejecución")


class EstadoPlanServicioDetalle(models.TextChoices):
    """Estados de un servicio dentro del plan del vehículo."""
    PENDIENTE = "PENDIENTE", _("Pendiente")
    PROGRAMADO = "PROGRAMADO", _("Programado")
    EN_PROCESO = "EN_PROCESO", _("En proceso")
    FINALIZADO = "FINALIZADO", _("Finalizado")
    INNECESARIO = "INNECESARIO", _("Innecesario")
    DIFERIDO = "DIFERIDO", _("Diferido")
    RECOMENDADO = "RECOMENDADO", _("Recomendado")


class OrigenPlanServicioDetalle(models.TextChoices):
    """Origen del servicio en el plan (quién lo agregó)."""
    CLIENTE = "CLIENTE", _("Cliente")
    ASESOR = "ASESOR", _("Asesor")
    ADMIN = "ADMIN", _("Administrador")
    MECANICO = "MECANICO", _("Mecánico")


class PrioridadServicio(models.TextChoices):
    """Prioridad de un servicio."""
    BAJA = "BAJA", _("Baja")
    MEDIA = "MEDIA", _("Media")
    ALTA = "ALTA", _("Alta")
    URGENTE = "URGENTE", _("Urgente")


class TipoEspacioTrabajo(models.TextChoices):
    """Tipos de espacios de trabajo en el taller."""
    TALLER = "TALLER", _("Taller")
    CHEQUEO = "CHEQUEO", _("Chequeo")
    GARAJE = "GARAJE", _("Garaje")
    LAVADO = "LAVADO", _("Lavado")


class EstadoEspacioTrabajo(models.TextChoices):
    """Estado de disponibilidad de un espacio de trabajo."""
    DISPONIBLE = "DISPONIBLE", _("Disponible")
    OCUPADO = "OCUPADO", _("Ocupado")
    MANTENIMIENTO = "MANTENIMIENTO", _("Mantenimiento")
    TIEMPO_EXTENDIDO = "TIEMPO_EXTENDIDO", _("Tiempo extendido")


class EstadoCita(models.TextChoices):
    """Estados de una cita."""
    PENDIENTE_APROBACION = "PENDIENTE_APROBACION", _("Pendiente de aprobación")
    PROGRAMADA = "PROGRAMADA", _("Programada")
    EN_ESPERA_INGRESO = "EN_ESPERA_INGRESO", _("En espera de ingreso")
    EN_PROCESO = "EN_PROCESO", _("En proceso")
    CANCELADA = "CANCELADA", _("Cancelada")
    NO_SHOW = "NO_SHOW", _("No asistió")
    FINALIZADA = "FINALIZADA", _("Finalizada")
    REPROGRAMADA = "REPROGRAMADA", _("Reprogramada")


class CanalOrigenCita(models.TextChoices):
    """Canal de origen de una cita."""
    CLIENTE = "CLIENTE", _("Cliente")
    ASESOR = "ASESOR", _("Asesor")


class TipoSegmentoCitaEspacio(models.TextChoices):
    """Tipo de segmento o fase en un espacio durante una cita."""
    CHEQUEO = "CHEQUEO", _("Chequeo")
    TALLER = "TALLER", _("Taller")
    LAVADO = "LAVADO", _("Lavado")
    GARAJE_ESPERA = "GARAJE_ESPERA", _("Garaje de espera")
    GARAJE_ENTREGA = "GARAJE_ENTREGA", _("Garaje de entrega")


class EstadoSegmentoCitaEspacio(models.TextChoices):
    """Estado de un segmento de cita en un espacio."""
    RESERVADO = "RESERVADO", _("Reservado")
    OCUPADO = "OCUPADO", _("Ocupado")
    FINALIZADO = "FINALIZADO", _("Finalizado")
    CANCELADO = "CANCELADO", _("Cancelado")
    EXTENDIDO = "EXTENDIDO", _("Extendido")

# ============================================================================
# MODELOS - TALLER AUTOMOTRIZ
# Sección 1: Vehículos y Plan General del Vehículo
# ============================================================================

class Vehiculo(models.Model):
    """
    Representa cada vehículo registrado en el taller.
    Un vehículo pertenece a un propietario (Usuario) y a una empresa.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="vehiculos",
        verbose_name=_("empresa"),
    )
    propietario = models.ForeignKey(
        Usuario,
        on_delete=models.RESTRICT,
        related_name="vehiculos",
        verbose_name=_("propietario"),
        help_text="Usuario propietario del vehículo"
    )
    placa = models.CharField(
        _("placa"),
        max_length=50,
        db_index=True,
        help_text="Placa del vehículo (única por empresa)"
    )
    marca = models.CharField(_("marca"), max_length=100)
    modelo = models.CharField(_("modelo"), max_length=100)
    anio = models.IntegerField(_("año"), help_text="Año de fabricación")
    color = models.CharField(_("color"), max_length=100, null=True, blank=True)
    kilometraje_actual = models.IntegerField(
        _("kilometraje actual"),
        default=0,
        help_text="Último kilometraje registrado"
    )
    vin_chasis = models.CharField(
        _("VIN/Chasis"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Número de identificación del vehículo"
    )
    motor = models.CharField(
        _("motor"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Tipo de motor"
    )
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Observaciones generales del vehículo"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoVehiculo.choices,
        default=EstadoVehiculo.ACTIVO,
        db_index=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "vehiculos"
        ordering = ["-created_at"]
        verbose_name = _("Vehículo")
        verbose_name_plural = _("Vehículos")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "placa"],
                name="unique_empresa_placa"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "placa"]),
            models.Index(fields=["propietario"]),
        ]

    def __str__(self):
        return f"{self.marca} {self.modelo} ({self.placa})"


class PlanServicioVehiculo(models.Model):
    """
    Plan general de servicios asociado a un vehículo.
    Agrupa todos los servicios pendientes, en proceso o resueltos para un vehículo.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="planes_servicio_vehiculo",
        verbose_name=_("empresa"),
    )
    vehiculo = models.OneToOneField(
        Vehiculo,
        on_delete=models.CASCADE,
        related_name="plan_servicio",
        verbose_name=_("vehículo"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=30,
        choices=EstadoPlanServicioVehiculo.choices,
        default=EstadoPlanServicioVehiculo.LIBRE,
        db_index=True,
    )
    descripcion_general = models.CharField(
        _("descripción general"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Descripción general del plan"
    )
    creado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="planes_creados",
        verbose_name=_("creado por"),
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "planes_servicio_vehiculo"
        ordering = ["-created_at"]
        verbose_name = _("Plan de Servicio del Vehículo")
        verbose_name_plural = _("Planes de Servicio del Vehículo")

    def __str__(self):
        return f"Plan {self.vehiculo.placa} ({self.estado})"


class ServicioCatalogo(models.Model):
    """
    Catálogo de servicios disponibles en el taller (por empresa).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="servicios_catalogo",
        verbose_name=_("empresa"),
    )
    codigo = models.CharField(
        _("código"),
        max_length=50,
        db_index=True,
        help_text="Código único del servicio (ej: CAMBIO_ACEITE)"
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    descripcion = models.CharField(
        _("descripción"),
        max_length=500,
        null=True,
        blank=True,
    )
    tiempo_estandar_min = models.IntegerField(
        _("tiempo estándar (minutos)"),
        help_text="Tiempo estándar de ejecución"
    )
    precio_base = models.DecimalField(
        _("precio base"),
        max_digits=12,
        decimal_places=2,
        help_text="Precio base del servicio"
    )
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "servicios_catalogo"
        ordering = ["nombre"]
        verbose_name = _("Servicio Catálogo")
        verbose_name_plural = _("Servicios Catálogo")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="unique_empresa_codigo_servicio"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "activo"]),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.codigo})"


class PlanServicioDetalle(models.Model):
    """
    Detalle de cada servicio dentro de un plan general del vehículo.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="planes_servicio_detalle",
        verbose_name=_("empresa"),
    )
    plan_servicio = models.ForeignKey(
        PlanServicioVehiculo,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("plan de servicio"),
    )
    servicio_catalogo = models.ForeignKey(
        ServicioCatalogo,
        on_delete=models.RESTRICT,
        related_name="planes_detalles",
        verbose_name=_("servicio catálogo"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPlanServicioDetalle.choices,
        default=EstadoPlanServicioDetalle.PENDIENTE,
        db_index=True,
    )
    origen = models.CharField(
        _("origen"),
        max_length=20,
        choices=OrigenPlanServicioDetalle.choices,
        help_text="Quién agregó este servicio"
    )
    prioridad = models.CharField(
        _("prioridad"),
        max_length=20,
        choices=PrioridadServicio.choices,
        default=PrioridadServicio.MEDIA,
    )
    tiempo_estandar_min = models.IntegerField(
        _("tiempo estándar (minutos)"),
        help_text="Tiempo estándar para este servicio"
    )
    precio_referencial = models.DecimalField(
        _("precio referencial"),
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Precio estimado"
    )
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
    )
    recomendado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="servicios_recomendados",
        verbose_name=_("recomendado por"),
        help_text="Si origen es MECANICO, usuario que recomendó"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "planes_servicio_detalle"
        ordering = ["plan_servicio", "prioridad", "-created_at"]
        verbose_name = _("Detalle Plan de Servicio")
        verbose_name_plural = _("Detalles Plan de Servicio")
        indexes = [
            models.Index(fields=["plan_servicio", "estado"]),
        ]

    def __str__(self):
        servicio_nombre = self.servicio_catalogo.nombre if self.servicio_catalogo else "S/C"
        return f"{servicio_nombre} ({self.estado})"


# ============================================================================
# Sección 2: Espacios y Horarios
# ============================================================================

class EspacioTrabajo(models.Model):
    """
    Representa cada espacio físico en el taller (taller, chequeo, garaje, lavado).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="espacios_trabajo",
        verbose_name=_("empresa"),
    )
    codigo = models.CharField(
        _("código"),
        max_length=50,
        db_index=True,
        help_text="Código único del espacio (ej: TALLER_1)"
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    tipo = models.CharField(
        _("tipo"),
        max_length=20,
        choices=TipoEspacioTrabajo.choices,
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoEspacioTrabajo.choices,
        default=EstadoEspacioTrabajo.DISPONIBLE,
        db_index=True,
    )
    activo = models.BooleanField(_("activo"), default=True)
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "espacios_trabajo"
        ordering = ["tipo", "nombre"]
        verbose_name = _("Espacio de Trabajo")
        verbose_name_plural = _("Espacios de Trabajo")
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "codigo"],
                name="unique_empresa_codigo_espacio"
            )
        ]
        indexes = [
            models.Index(fields=["empresa", "tipo", "estado"]),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.tipo})"


class HorarioEspacioTrabajo(models.Model):
    """
    Horarios de disponibilidad de cada espacio (por día de la semana).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="horarios_espacios",
        verbose_name=_("empresa"),
    )
    espacio_trabajo = models.ForeignKey(
        EspacioTrabajo,
        on_delete=models.CASCADE,
        related_name="horarios",
        verbose_name=_("espacio de trabajo"),
    )
    dia_semana = models.IntegerField(
        _("día de la semana"),
        choices=[
            (0, _("Lunes")),
            (1, _("Martes")),
            (2, _("Miércoles")),
            (3, _("Jueves")),
            (4, _("Viernes")),
            (5, _("Sábado")),
            (6, _("Domingo")),
        ],
        help_text="0=Lunes, 6=Domingo"
    )
    hora_inicio = models.TimeField(_("hora inicio"))
    hora_fin = models.TimeField(_("hora fin"))
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "horarios_espacios_trabajo"
        ordering = ["espacio_trabajo", "dia_semana"]
        verbose_name = _("Horario Espacio de Trabajo")
        verbose_name_plural = _("Horarios Espacios de Trabajo")
        indexes = [
            models.Index(fields=["espacio_trabajo", "dia_semana"]),
        ]

    def __str__(self):
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return f"{self.espacio_trabajo.nombre} - {dias[self.dia_semana]} {self.hora_inicio}-{self.hora_fin}"


# ============================================================================
# Sección 3: Citas y Segmentos de Espacio
# ============================================================================

class Cita(models.Model):
    """
    Representa una cita/ingreso del vehículo al taller.
    Una cita puede tener múltiples servicios (PlanServicioDetalle) y múltiples espacios.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="citas",
        verbose_name=_("empresa"),
    )
    vehiculo = models.ForeignKey(
        Vehiculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas",
        verbose_name=_("vehículo"),
    )
    cliente = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_cliente",
        verbose_name=_("cliente"),
        help_text="Usuario cliente/propietario"
    )
    plan_servicio = models.ForeignKey(
        PlanServicioVehiculo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas",
        verbose_name=_("plan de servicio"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=30,
        choices=EstadoCita.choices,
        default=EstadoCita.PROGRAMADA,
        db_index=True,
    )
    canal_origen = models.CharField(
        _("canal de origen"),
        max_length=20,
        choices=CanalOrigenCita.choices,
        help_text="Quién agendó la cita"
    )
    fecha_hora_inicio_programada = models.DateTimeField(_("inicio programado"))
    fecha_hora_fin_programada = models.DateTimeField(_("fin programado"))
    duracion_estimada_min = models.IntegerField(
        _("duración estimada (minutos)"),
        help_text="Duración estimada de la cita"
    )
    llegada_real_at = models.DateTimeField(
        _("llegada real"),
        null=True,
        blank=True,
        help_text="Cuándo llegó el vehículo efectivamente"
    )
    reprogramaciones_count = models.IntegerField(
        _("cantidad de reprogramaciones"),
        default=0,
        help_text="Número de veces que se reprogramó"
    )
    ultima_reprogramacion_at = models.DateTimeField(
        _("última reprogramación"),
        null=True,
        blank=True,
    )
    motivo_ultima_reprogramacion = models.CharField(
        _("motivo de última reprogramación"),
        max_length=500,
        null=True,
        blank=True,
    )
    motivo_visita = models.CharField(
        _("motivo de la visita"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Resumen de por qué el cliente trae el vehículo"
    )
    observaciones_cliente = models.CharField(
        _("observaciones del cliente"),
        max_length=500,
        null=True,
        blank=True,
    )
    asesor_responsable = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_asesor",
        verbose_name=_("asesor responsable"),
    )
    cancelada_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_canceladas",
        verbose_name=_("cancelada por"),
    )
    motivo_cancelacion = models.CharField(
        _("motivo de cancelación"),
        max_length=500,
        null=True,
        blank=True,
    )
    no_show_marcado_at = models.DateTimeField(
        _("marcado como no-show en"),
        null=True,
        blank=True,
    )
    finalizada_at = models.DateTimeField(
        _("finalizada en"),
        null=True,
        blank=True,
    )
    vehiculo_devuelto_at = models.DateTimeField(
        _("vehículo devuelto en"),
        null=True,
        blank=True,
        help_text="Cuándo se marcó el vehículo como recolectado/devuelto al cliente"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "citas"
        ordering = ["-fecha_hora_inicio_programada"]
        verbose_name = _("Cita")
        verbose_name_plural = _("Citas")
        indexes = [
            models.Index(fields=["empresa", "estado", "-fecha_hora_inicio_programada"]),
            models.Index(fields=["vehiculo"]),
            models.Index(fields=["cliente"]),
        ]

    def __str__(self):
        return f"Cita {self.id} - {self.vehiculo.placa if self.vehiculo else 'S/V'} ({self.estado})"


class CitaEspacioSegmento(models.Model):
    """
    Representa cada segmento/fase de una cita en un espacio específico.
    Una cita puede pasar por varios espacios en diferentes momentos.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="citas_espacios_segmentos",
        verbose_name=_("empresa"),
    )
    cita = models.ForeignKey(
        Cita,
        on_delete=models.CASCADE,
        related_name="espacios_segmentos",
        verbose_name=_("cita"),
    )
    espacio_trabajo = models.ForeignKey(
        EspacioTrabajo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_segmentos",
        verbose_name=_("espacio de trabajo"),
    )
    orden_segmento = models.IntegerField(
        _("orden del segmento"),
        help_text="Orden en que ocurren los segmentos en la cita (1, 2, 3...)"
    )
    tipo_segmento = models.CharField(
        _("tipo de segmento"),
        max_length=20,
        choices=TipoSegmentoCitaEspacio.choices,
    )
    estado_segmento = models.CharField(
        _("estado del segmento"),
        max_length=20,
        choices=EstadoSegmentoCitaEspacio.choices,
        default=EstadoSegmentoCitaEspacio.RESERVADO,
        db_index=True,
    )
    inicio_programado = models.DateTimeField(_("inicio programado"))
    fin_programado = models.DateTimeField(_("fin programado"))
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
    motivo = models.CharField(
        _("motivo"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Motivo de cambios o observaciones"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "citas_espacios_segmentos"
        ordering = ["cita", "orden_segmento"]
        verbose_name = _("Segmento Cita-Espacio")
        verbose_name_plural = _("Segmentos Cita-Espacio")
        indexes = [
            models.Index(fields=["cita", "orden_segmento"]),
        ]

    def __str__(self):
        return f"Cita {self.cita.id} - Seg {self.orden_segmento} ({self.tipo_segmento})"

class CitaDetalle(models.Model):
    """
    Detalle de cada servicio (plan detail) seleccionado para una cita específica.
    
    Propósito:
    1. Trazabilidad: guardar qué detalles del plan se programaron en esa cita
    2. Validación: evitar que el mismo detalle del plan esté en dos citas activas
    3. Historicidad: snapshot de datos del detalle en el momento de la cita
    4. Estadística: poder saber cuándo cambió de estado cada servicio
    
    Relaciones:
    - cita: referencia a la Cita que contiene este servicio
    - plan_detalle: referencia al PlanServicioDetalle original del plan del vehículo
    - estado: estado actual del detalle dentro de la cita (PENDIENTE, PROGRAMADO, etc)
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="citas_detalles",
        verbose_name=_("empresa"),
    )
    cita = models.ForeignKey(
        Cita,
        on_delete=models.CASCADE,
        related_name="detalles",
        verbose_name=_("cita"),
        help_text="Referencia a la cita que contiene este detalle"
    )
    plan_detalle = models.ForeignKey(
        PlanServicioDetalle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_detalles",
        verbose_name=_("detalle del plan"),
        help_text="Referencia al detalle original del plan del vehículo"
    )
    servicio_catalogo = models.ForeignKey(
        ServicioCatalogo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="citas_detalles",
        verbose_name=_("servicio catálogo (snapshot)"),
        help_text="Copia del servicio al momento de la cita (para historicidad)"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPlanServicioDetalle.choices,
        default=EstadoPlanServicioDetalle.PROGRAMADO,
        db_index=True,
        help_text="Estado del detalle dentro de la cita"
    )
    tiempo_estandar_min = models.IntegerField(
        _("tiempo estándar (minutos)"),
        help_text="Copia snapshot del tiempo estándar al momento de la cita"
    )
    precio_referencial = models.DecimalField(
        _("precio referencial"),
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Copia snapshot del precio al momento de la cita"
    )
    observaciones = models.CharField(
        _("observaciones"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Observaciones específicas para este detalle en esta cita"
    )
    orden_visual = models.IntegerField(
        _("orden visual"),
        default=0,
        help_text="Orden en que se muestra en la lista de la cita"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "citas_detalles"
        ordering = ["cita", "orden_visual", "created_at"]
        verbose_name = _("Detalle de Cita")
        verbose_name_plural = _("Detalles de Cita")
        indexes = [
            models.Index(fields=["cita", "estado"]),
            models.Index(fields=["plan_detalle", "estado"]),
            models.Index(fields=["empresa", "estado"]),
        ]
        constraints = [
            # No permitir el mismo plan_detalle en dos CitaDetalle de citas activas
            # Esta validación se hace en la aplicación por complejidad SQL
            models.UniqueConstraint(
                fields=["cita", "plan_detalle"],
                name="unique_cita_plan_detalle"
            )
        ]

    def __str__(self):
        servicio = self.servicio_catalogo.nombre if self.servicio_catalogo else "N/A"
        return f"CitaDetalle {self.cita.id} - {servicio} ({self.estado})"

