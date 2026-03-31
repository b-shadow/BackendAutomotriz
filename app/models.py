"""
Modelos de la aplicación SaaS multi-tenant.

Estructura alineada con base de datos PostgreSQL existente:
  - Empresa: Cada empresa/organización (instancia del SaaS)
  - Plan: Planes de suscripción disponibles
  - Rol: Roles de usuario (por empresa o sistema)
  - Usuario: Usuarios del sistema (vinculados a empresa, AUTH_USER_MODEL)
  - Suscripcion: Qué plan tiene cada empresa y su estado
  - Auditoria: Log de acciones para compliance
"""
import uuid
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.utils.translation import gettext_lazy as _
from app.managers import UsuarioManager


# ============================================================================
# ENUMS / CHOICES
# ============================================================================

class EstadoEmpresa(models.TextChoices):
    ACTIVA = "ACTIVA", _("Activa")
    INACTIVA = "INACTIVA", _("Inactiva")


class EstadoSuscripcion(models.TextChoices):
    ACTIVA = "ACTIVA", _("Activa")
    PAUSADA = "PAUSADA", _("Pausada")
    CANCELADA = "CANCELADA", _("Cancelada")


# ============================================================================
# MODELOS
# ============================================================================

class Empresa(models.Model):
    """
    Representa cada empresa/cliente del SaaS.
    Cada empresa es una instancia separada y completa del sistema.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nombre = models.CharField(
        _("nombre"),
        max_length=255,
        help_text="Nombre legal de la empresa"
    )
    slug = models.CharField(
        _("slug"),
        max_length=255,
        unique=True,
        db_index=True,
        help_text="Identificador único para URL (ej: acme, globex)"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoEmpresa.choices,
        default=EstadoEmpresa.ACTIVA,
        db_index=True,
    )
    suscripcion_hasta = models.DateTimeField(
        _("suscripción hasta"),
        null=True,
        blank=True,
        help_text="Fecha de vencimiento de la suscripción actual"
    )
    stripe_customer_id = models.CharField(
        _("Stripe Customer ID"),
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="ID del customer en Stripe para facturación"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "empresas"
        ordering = ["-created_at"]
        verbose_name = _("Empresa")
        verbose_name_plural = _("Empresas")
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        return f"{self.nombre} ({self.slug})"


class Plan(models.Model):
    """
    Planes de suscripción disponibles en el SaaS.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(
        _("código"),
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Código único del plan (ej: STARTER, PRO, ENTERPRISE)"
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    descripcion = models.CharField(_("descripción"), max_length=500, null=True, blank=True)
    duracion_dias = models.IntegerField(
        _("duración (días)"),
        help_text="Período de facturación en días (30, 365, etc)"
    )
    precio_centavos = models.IntegerField(
        _("precio (centavos)"),
        default=0,
        help_text="Precio en centavos para evitar decimales"
    )
    moneda = models.CharField(
        _("moneda"),
        max_length=3,
        default="USD",
        help_text="Código de moneda ISO (USD, EUR, CLP)"
    )
    activo = models.BooleanField(_("activo"), default=True)
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "planes"
        ordering = ["precio_centavos"]
        verbose_name = _("Plan")
        verbose_name_plural = _("Planes")

    def __str__(self):
        return f"{self.nombre} (${self.precio_centavos / 100})"

    @property
    def precio_formateado(self):
        """Retorna el precio formateado como string."""
        return f"{self.precio_centavos / 100:.2f}"


class Rol(models.Model):
    """
    Roles de usuario dentro de una empresa.
    Puede ser un rol de sistema (global) o específico de la empresa.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("empresa"),
    )
    nombre = models.CharField(_("nombre"), max_length=100)
    descripcion = models.CharField(_("descripción"), max_length=500, null=True, blank=True)
    es_sistema = models.BooleanField(
        _("es sistema"),
        default=False,
        help_text="Si es True, es un rol del sistema (no editable por usuarios)"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "roles"
        ordering = ["nombre"]
        verbose_name = _("Rol")
        verbose_name_plural = _("Roles")
        unique_together = [("empresa", "nombre")]

    def __str__(self):
        return f"{self.nombre} ({self.empresa.nombre})"


class Usuario(AbstractBaseUser, PermissionsMixin):
    """
    Modelo de Usuario como AUTH_USER_MODEL.
    
    ESTRUCTURA MULTI-TENANT:
    - Cada usuario pertenece a UNA sola empresa
    - Autenticación por email dentro del contexto de esa empresa
    - USERNAME_FIELD = "email" (único dentro de empresa, no globalmente)
    
    HERENCIA:
    - AbstractBaseUser proporciona password y last_login
    - PermissionsMixin proporciona is_staff, is_superuser, groups, permissions
    
    BÚSQUEDA MULTI-TENANT:
    - Usuario.objects.filter(empresa=empresa, email=email)
    - Usar UsuarioManager para abstracción correcta
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # MULTI-TENANT
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="usuarios",
        verbose_name=_("empresa"),
    )
    rol = models.ForeignKey(
        Rol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usuarios",
        verbose_name=_("rol"),
    )
    
    # AUTENTICACIÓN
    email = models.EmailField(
        _("email"),
        max_length=255,
        db_index=True,
        unique=False,  # No unique globalmente; único por (empresa, email) vía UniqueConstraint
        help_text="Email único dentro de la empresa (no bloqueado globalmente)"
    )
    
    # DATOS PERSONALES
    nombres = models.CharField(_("nombres"), max_length=255)
    apellidos = models.CharField(_("apellidos"), max_length=255, null=True, blank=True)
    telefono = models.CharField(_("teléfono"), max_length=20, null=True, blank=True)
    
    # ESTADO
    is_active = models.BooleanField(
        _("activo"),
        default=True,
        db_index=True,
        help_text="Designa si el usuario puede iniciar sesión"
    )
    
    # PERMISOS Y ADMINISTRACIÓN
    # is_staff DEBE definirse explícitamente aquí: PermissionsMixin NO lo proporciona.
    # Solo hereda is_superuser, groups y user_permissions.
    # Sin esta definición explícita, el campo no existiría en BD y el manager/admin sería inconsistente.
    is_staff = models.BooleanField(
        _("staff"),
        default=False,
        db_index=True,
        help_text="Designa si el usuario puede acceder al panel admin de Django"
    )
    
    # PREFERENCIAS DE NOTIFICACIÓN
    noti_email = models.BooleanField(
        _("notificación por email"),
        default=True,
        help_text="Indica si el usuario desea recibir notificaciones por email"
    )
    noti_push = models.BooleanField(
        _("notificación push"),
        default=True,
        help_text="Indica si el usuario desea recibir notificaciones push"
    )
    
    # AUTENTICACIÓN - SESIONES
    session_revoked_at = models.DateTimeField(
        _("sesión revocada en"),
        null=True,
        blank=True,
        db_index=True,
        help_text="Si está seteado, todos los tokens emitidos antes de esta fecha son inválidos"
    )
    
    # AUDITORÍA
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)
    
    # AbstractBaseUser proporciona:
    # - password (hasheado automáticamente)
    # - last_login (se actualiza automáticamente)
    # PermissionsMixin proporciona:
    # - is_superuser, groups, user_permissions
    # Usuario define explícitamente:
    # - is_staff (claridad + control + migración explícita)

    # MANAGER
    objects = UsuarioManager()
    
    # CONFIGURACIÓN DE AUTENTICACIÓN DJANGO
    # Multi-tenant: email no es único globalmente, es único por (empresa, email)
    # USERNAME_FIELD se usa solo en contextos no-tenant (admin Django)
    # En login tenant, búsqueda se hace por (empresa, email) en serializers
    USERNAME_FIELD = "id"  # Usar id como USERNAME_FIELD (único globalmente) 
    REQUIRED_FIELDS = []  # No requerimos campos adicionales en creación

    class Meta:
        db_table = "usuarios"
        ordering = ["-created_at"]
        verbose_name = _("Usuario")
        verbose_name_plural = _("Usuarios")
        indexes = [
            models.Index(fields=["empresa", "email"]),
            models.Index(fields=["email"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["empresa", "email"],
                name="unique_empresa_email"
            )
        ]

    def __str__(self):
        return f"{self.nombres} ({self.email}) - {self.empresa.nombre}"

    def get_full_name(self):
        """Retorna nombre completo del usuario."""
        return f"{self.nombres} {self.apellidos or ''}".strip()

    def get_short_name(self):
        """Retorna solo los nombres."""
        return self.nombres


class Suscripcion(models.Model):
    """
    Suscripción activa de una empresa a un plan.
    Controla qué plan tiene la empresa y cuándo vence.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.OneToOneField(
        Empresa,
        on_delete=models.CASCADE,
        related_name="suscripcion",
        verbose_name=_("empresa"),
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suscripciones",
        verbose_name=_("plan"),
    )
    inicio = models.DateTimeField(_("inicio"))
    fin = models.DateTimeField(_("fin"))
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoSuscripcion.choices,
        default=EstadoSuscripcion.ACTIVA,
        db_index=True,
    )
    renovacion_de = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="renovaciones",
        verbose_name=_("renovación de"),
        help_text="Si es renovación, referencia a la suscripción anterior"
    )
    referencia_pago = models.CharField(
        _("referencia de pago"),
        max_length=255,
        null=True,
        blank=True,
        help_text="ID del pago en proveedor de pagos (Stripe, etc)"
    )
    plan_pendiente = models.ForeignKey(
        Plan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suscripciones_pendiente",
        verbose_name=_("plan pendiente"),
        help_text="Plan que se aplicará después de terminar el período actual"
    )
    fecha_aplicacion_plan_pendiente = models.DateTimeField(
        _("fecha de aplicación del plan pendiente"),
        null=True,
        blank=True,
        help_text="Fecha exacta en la que el plan pendiente pasa a ser el plan actual"
    )
    pago_plan_pendiente = models.OneToOneField(
        "Pago",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="suscripcion_plan_pendiente",
        verbose_name=_("pago del plan pendiente"),
        help_text=(
            "Referencia AL REGISTRO ACTUAL del pago confirmado para el cambio pendiente. "
            "Este es un VINCULO al pago actualmente asociado con plan_pendiente. "
            "El historial completo de todos los pagos permanece en la tabla Pago (nunca se eliminan). "
            "Cuando se aplica el plan_pendiente automáticamente, este campo se limpia (SET_NULL). "
            "Un solo pago confirmado puede estar vinculado a la vez."
        )
    )
    notas = models.CharField(
        _("notas"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Notas internas sobre la suscripción"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "suscripciones"
        ordering = ["-created_at"]
        verbose_name = _("Suscripción")
        verbose_name_plural = _("Suscripciones")
        indexes = [
            models.Index(fields=["empresa", "estado"]),
        ]

    def __str__(self):
        return f"{self.empresa.nombre} - {self.plan.nombre} ({self.estado})"


class Auditoria(models.Model):
    """
    Log de auditoría de todas las acciones importantes.
    Crítico para compliance y debugging.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="eventos_auditoria",
        verbose_name=_("empresa"),
    )
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_generados",
        verbose_name=_("usuario"),
    )
    accion = models.CharField(
        _("acción"),
        max_length=100,
        db_index=True,
        help_text="Tipo de acción (crear, actualizar, eliminar, login, etc)"
    )
    entidad_tipo = models.CharField(
        _("tipo de entidad"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Modelo sobre el que se actuó (Usuario, Empresa, etc)"
    )
    entidad_id = models.UUIDField(
        _("ID de entidad"),
        null=True,
        blank=True,
        help_text="UUID de la entidad modificada"
    )
    descripcion = models.CharField(
        _("descripción"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Descripción legible de la acción"
    )
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        help_text="Datos adicionales en JSON (cambios, valores antiguos, etc)"
    )
    ip = models.GenericIPAddressField(
        _("IP"),
        null=True,
        blank=True,
        help_text="IP desde donde se realizó la acción"
    )
    user_agent = models.CharField(
        _("user agent"),
        max_length=500,
        null=True,
        blank=True,
        help_text="User-Agent del cliente"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True, db_index=True)

    class Meta:
        db_table = "auditoria"
        ordering = ["-created_at"]
        verbose_name = _("Auditoría")
        verbose_name_plural = _("Auditorías")
        indexes = [
            models.Index(fields=["empresa", "-created_at"]),
            models.Index(fields=["usuario", "accion"]),
        ]

    def __str__(self):
        return f"{self.accion} - {self.entidad_tipo} ({self.created_at})"

class EstadoPago(models.TextChoices):
    """Estados de un pago."""
    PENDIENTE = "PENDIENTE", _("Pendiente")
    COMPLETADO = "COMPLETADO", _("Completado")
    FALLIDO = "FALLIDO", _("Fallido")
    CANCELADO = "CANCELADO", _("Cancelado")
    REEMBOLSO = "REEMBOLSO", _("Reembolso")


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


class TipoAvanceVehiculo(models.TextChoices):
    """Tipo de avance reportado en una cita."""
    GENERAL = "GENERAL", _("General")
    SERVICIO = "SERVICIO", _("Servicio específico")


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


class CanalEntregaNotificacion(models.TextChoices):
    """Canales de entrega de notificaciones."""
    WEB = "WEB", _("Web")
    EMAIL = "EMAIL", _("Email")


class EstadoEntregaNotificacion(models.TextChoices):
    """Estado de entrega de una notificación."""
    PENDIENTE = "PENDIENTE", _("Pendiente")
    ENVIADO = "ENVIADO", _("Enviado")
    FALLIDO = "FALLIDO", _("Fallido")


class CanalConversacionIA(models.TextChoices):
    """Canales de conversación con IA."""
    WEB = "WEB", _("Web")
    MOVIL = "MOVIL", _("Móvil")


class RolMensajeIA(models.TextChoices):
    """Rol del mensaje en una conversación IA."""
    USUARIO = "USUARIO", _("Usuario")
    ASISTENTE = "ASISTENTE", _("Asistente")
    SISTEMA = "SISTEMA", _("Sistema")


class TipoReporteGenerado(models.TextChoices):
    """Tipos de reportes generados."""
    VEHICULO = "VEHICULO", _("Vehículo")
    PRESUPUESTO = "PRESUPUESTO", _("Presupuesto")
    INVENTARIO = "INVENTARIO", _("Inventario")
    GLOBAL = "GLOBAL", _("Global")


class FormatoReporteGenerado(models.TextChoices):
    """Formatos de exportación de reportes."""
    PDF = "PDF", _("PDF")
    CSV = "CSV", _("CSV")
    HTML = "HTML", _("HTML")


class Pago(models.Model):
    """
    Modelo para registrar pagos con Stripe.
    Se usa al registrar nuevas empresas para cobrar la suscripción inicial.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Datos del registro (antes de crear empresa)
    empresa_slug = models.CharField(
        _("slug de empresa"),
        max_length=255,
        help_text="Slug de la empresa a crear"
    )
    empresa_nombre = models.CharField(
        _("nombre de empresa"),
        max_length=255,
        help_text="Nombre de la empresa a crear"
    )
    
    # Datos del usuario admin
    usuario_email = models.CharField(
        _("email del usuario"),
        max_length=255,
        help_text="Email del usuario admin a crear"
    )
    usuario_nombres = models.CharField(
        _("nombres del usuario"),
        max_length=255,
        help_text="Nombres del usuario admin"
    )
    usuario_apellidos = models.CharField(
        _("apellidos del usuario"),
        max_length=255,
        null=True,
        blank=True,
        help_text="Apellidos del usuario admin"
    )
    usuario_password = models.CharField(
        _("password del usuario"),
        max_length=255,
        null=True,
        blank=True,
        help_text="Password sin hashar (se hasheará al crear el usuario)"
    )
    
    # Plan seleccionado
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="pagos",
        verbose_name=_("plan"),
    )
    
    # Información del pago
    amount_centavos = models.IntegerField(
        _("monto (centavos)"),
        help_text="Monto en centavos"
    )
    moneda = models.CharField(
        _("moneda"),
        max_length=3,
        default="USD",
        help_text="Código de moneda ISO (USD, EUR, CLP)"
    )
    
    # Referencias de Stripe
    stripe_payment_intent_id = models.CharField(
        _("Stripe Payment Intent ID"),
        max_length=255,
        unique=True,
        db_index=True,
        help_text="ID del Payment Intent de Stripe"
    )
    stripe_session_id = models.CharField(
        _("Stripe Session ID"),
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        help_text="ID de la Checkout Session (si usa Hosted Checkout)"
    )
    stripe_customer_id = models.CharField(
        _("Stripe Customer ID"),
        max_length=255,
        null=True,
        blank=True,
        help_text="ID del customer en Stripe"
    )
    
    # Estado del pago
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoPago.choices,
        default=EstadoPago.PENDIENTE,
        db_index=True,
    )
    
    # Empresa creada (si está completado)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="pagos_iniciales",
        verbose_name=_("empresa"),
        help_text="Empresa creada tras pago exitoso"
    )
    
    # Metadata
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        help_text="Datos adicionales (ej: IP, user agent, etc)"
    )
    
    # Timestamps
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)
    processed_at = models.DateTimeField(
        _("procesado en"),
        null=True,
        blank=True,
        help_text="Cuándo se procesó el pago exitosamente"
    )

    class Meta:
        db_table = "pagos"
        ordering = ["-created_at"]
        verbose_name = _("Pago")
        verbose_name_plural = _("Pagos")
        indexes = [
            models.Index(fields=["stripe_payment_intent_id"]),
            models.Index(fields=["empresa_slug"]),
            models.Index(fields=["usuario_email"]),
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self):
        # Convertir UUID a string antes de hacer slicing para evitar errores de tipo
        return f"Pago {str(self.id)[:8]} - {self.empresa_nombre} ({self.estado})"


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


# ============================================================================
# Sección 11: Notificaciones
# ============================================================================

class Notificacion(models.Model):
    """
    Notificaciones para usuarios.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="notificaciones",
        verbose_name=_("empresa"),
    )
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="notificaciones_recibidas",
        verbose_name=_("usuario"),
    )
    tipo = models.CharField(
        _("tipo"),
        max_length=100,
        help_text="Tipo de notificación (ej: cita_programada, pago_recibido)"
    )
    titulo = models.CharField(_("título"), max_length=255)
    mensaje = models.CharField(_("mensaje"), max_length=500)
    entidad_tipo = models.CharField(
        _("tipo de entidad"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Tipo de entidad relacionada (Cita, Pago, etc)"
    )
    entidad_id = models.UUIDField(
        _("ID de entidad"),
        null=True,
        blank=True,
        help_text="ID de la entidad relacionada"
    )
    leida_at = models.DateTimeField(
        _("leída en"),
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "notificaciones"
        ordering = ["-created_at"]
        verbose_name = _("Notificación")
        verbose_name_plural = _("Notificaciones")
        indexes = [
            models.Index(fields=["usuario", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.titulo} para {self.usuario.nombres}"


class NotificacionEntrega(models.Model):
    """
    Registro de entrega de notificaciones por canal.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="notificaciones_entrega",
        verbose_name=_("empresa"),
    )
    notificacion = models.ForeignKey(
        Notificacion,
        on_delete=models.CASCADE,
        related_name="entregas",
        verbose_name=_("notificación"),
    )
    canal = models.CharField(
        _("canal"),
        max_length=20,
        choices=CanalEntregaNotificacion.choices,
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoEntregaNotificacion.choices,
        default=EstadoEntregaNotificacion.PENDIENTE,
        db_index=True,
    )
    destinatario = models.CharField(
        _("destinatario"),
        max_length=255,
        help_text="Email, token push, etc"
    )
    enviado_at = models.DateTimeField(
        _("enviado en"),
        null=True,
        blank=True,
    )
    error_mensaje = models.CharField(
        _("mensaje de error"),
        max_length=500,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "notificaciones_entrega"
        ordering = ["-created_at"]
        verbose_name = _("Entrega Notificación")
        verbose_name_plural = _("Entregas Notificaciones")
        indexes = [
            models.Index(fields=["notificacion", "canal"]),
        ]

    def __str__(self):
        return f"{self.notificacion.titulo} - {self.canal} ({self.estado})"


# ============================================================================
# Sección 12: IA
# ============================================================================

class ConversacionIA(models.Model):
    """
    Conversación con asistente IA.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="conversaciones_ia",
        verbose_name=_("empresa"),
    )
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="conversaciones_ia",
        verbose_name=_("usuario"),
    )
    estado = models.CharField(
        _("estado"),
        max_length=50,
        default="ACTIVA",
        help_text="ACTIVA, ARCHIVADA, CERRADA"
    )
    canal = models.CharField(
        _("canal"),
        max_length=20,
        choices=CanalConversacionIA.choices,
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "conversaciones_ia"
        ordering = ["-updated_at"]
        verbose_name = _("Conversación IA")
        verbose_name_plural = _("Conversaciones IA")
        indexes = [
            models.Index(fields=["usuario", "-updated_at"]),
        ]

    def __str__(self):
        return f"Conv {self.id} - {self.usuario.nombres}"


class MensajeIA(models.Model):
    """
    Mensaje en una conversación IA.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="mensajes_ia",
        verbose_name=_("empresa"),
    )
    conversacion = models.ForeignKey(
        ConversacionIA,
        on_delete=models.CASCADE,
        related_name="mensajes",
        verbose_name=_("conversación"),
    )
    rol_mensaje = models.CharField(
        _("rol del mensaje"),
        max_length=20,
        choices=RolMensajeIA.choices,
        help_text="USUARIO, ASISTENTE, SISTEMA"
    )
    contenido = models.TextField(_("contenido"))
    metadata = models.JSONField(
        _("metadata"),
        default=dict,
        help_text="Datos adicionales (tokens, modelo, etc)"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "mensajes_ia"
        ordering = ["conversacion", "created_at"]
        verbose_name = _("Mensaje IA")
        verbose_name_plural = _("Mensajes IA")
        indexes = [
            models.Index(fields=["conversacion", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.rol_mensaje}: {self.contenido[:50]}"


class AccionIA(models.Model):
    """
    Acción sugerida/solicitada desde conversación IA.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="acciones_ia",
        verbose_name=_("empresa"),
    )
    conversacion = models.ForeignKey(
        ConversacionIA,
        on_delete=models.CASCADE,
        related_name="acciones",
        verbose_name=_("conversación"),
    )
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name="acciones_ia",
        verbose_name=_("usuario"),
    )
    accion = models.CharField(
        _("acción"),
        max_length=100,
        help_text="Código de la acción (ej: crear_cita, registrar_pago)"
    )
    parametros = models.JSONField(
        _("parámetros"),
        default=dict,
        help_text="Parámetros de la acción"
    )
    estado = models.CharField(
        _("estado"),
        max_length=50,
        default="PENDIENTE",
        help_text="PENDIENTE, CONFIRMADA, EJECUTADA, CANCELADA"
    )
    requiere_confirmacion = models.BooleanField(
        _("requiere confirmación"),
        default=False,
    )
    confirmada_at = models.DateTimeField(
        _("confirmada en"),
        null=True,
        blank=True,
    )
    ejecutada_at = models.DateTimeField(
        _("ejecutada en"),
        null=True,
        blank=True,
    )
    resultado = models.JSONField(
        _("resultado"),
        default=dict,
        help_text="Resultado de la ejecución"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)

    class Meta:
        db_table = "acciones_ia"
        ordering = ["-created_at"]
        verbose_name = _("Acción IA")
        verbose_name_plural = _("Acciones IA")
        indexes = [
            models.Index(fields=["conversacion", "estado"]),
        ]

    def __str__(self):
        return f"{self.accion} ({self.estado})"


# ============================================================================
# Sección 13: Reportes Generados
# ============================================================================

class ReporteGenerado(models.Model):
    """
    Reportes generados por usuarios.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="reportes_generados",
        verbose_name=_("empresa"),
    )
    tipo_reporte = models.CharField(
        _("tipo de reporte"),
        max_length=20,
        choices=TipoReporteGenerado.choices,
    )
    formato = models.CharField(
        _("formato"),
        max_length=20,
        choices=FormatoReporteGenerado.choices,
    )
    filtros = models.JSONField(
        _("filtros"),
        default=dict,
        help_text="Filtros usados para generar el reporte"
    )
    archivo_url = models.CharField(
        _("URL del archivo"),
        max_length=500,
        null=True,
        blank=True,
        help_text="URL del archivo generado"
    )
    generado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reportes_generados",
        verbose_name=_("generado por"),
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "reportes_generados"
        ordering = ["-created_at"]
        verbose_name = _("Reporte Generado")
        verbose_name_plural = _("Reportes Generados")
        indexes = [
            models.Index(fields=["generado_por", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.tipo_reporte} - {self.formato}"