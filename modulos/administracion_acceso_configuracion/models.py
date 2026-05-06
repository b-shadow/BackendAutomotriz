"""Modelos del modulo 3.5.1 Administracion, Acceso y Configuracion."""

import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _

from modulos.administracion_acceso_configuracion.managers import UsuarioManager

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
        help_text="Identificador Ãºnico para URL (ej: acme, globex)"
    )
    estado = models.CharField(
        _("estado"),
        max_length=20,
        choices=EstadoEmpresa.choices,
        default=EstadoEmpresa.ACTIVA,
        db_index=True,
    )
    suscripcion_hasta = models.DateTimeField(
        _("suscripciÃ³n hasta"),
        null=True,
        blank=True,
        help_text="Fecha de vencimiento de la suscripciÃ³n actual"
    )
    stripe_customer_id = models.CharField(
        _("Stripe Customer ID"),
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        db_index=True,
        help_text="ID del customer en Stripe para facturaciÃ³n"
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
    Planes de suscripciÃ³n disponibles en el SaaS.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    codigo = models.CharField(
        _("cÃ³digo"),
        max_length=100,
        unique=True,
        db_index=True,
        help_text="CÃ³digo Ãºnico del plan (ej: STARTER, PRO, ENTERPRISE)"
    )
    nombre = models.CharField(_("nombre"), max_length=255)
    descripcion = models.CharField(_("descripciÃ³n"), max_length=500, null=True, blank=True)
    duracion_dias = models.IntegerField(
        _("duraciÃ³n (dÃ­as)"),
        help_text="PerÃ­odo de facturaciÃ³n en dÃ­as (30, 365, etc)"
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
        help_text="CÃ³digo de moneda ISO (USD, EUR, CLP)"
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
    Puede ser un rol de sistema (global) o especÃ­fico de la empresa.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey(
        Empresa,
        on_delete=models.CASCADE,
        related_name="roles",
        verbose_name=_("empresa"),
    )
    nombre = models.CharField(_("nombre"), max_length=100)
    descripcion = models.CharField(_("descripciÃ³n"), max_length=500, null=True, blank=True)
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
    - AutenticaciÃ³n por email dentro del contexto de esa empresa
    - USERNAME_FIELD = "email" (Ãºnico dentro de empresa, no globalmente)
    
    HERENCIA:
    - AbstractBaseUser proporciona password y last_login
    - PermissionsMixin proporciona is_staff, is_superuser, groups, permissions
    
    BÃšSQUEDA MULTI-TENANT:
    - Usuario.objects.filter(empresa=empresa, email=email)
    - Usar UsuarioManager para abstracciÃ³n correcta
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
    
    # AUTENTICACIÃ“N
    email = models.EmailField(
        _("email"),
        max_length=255,
        db_index=True,
        unique=False,  # No unique globalmente; Ãºnico por (empresa, email) vÃ­a UniqueConstraint
        help_text="Email Ãºnico dentro de la empresa (no bloqueado globalmente)"
    )
    
    # DATOS PERSONALES
    nombres = models.CharField(_("nombres"), max_length=255)
    apellidos = models.CharField(_("apellidos"), max_length=255, null=True, blank=True)
    telefono = models.CharField(_("telÃ©fono"), max_length=20, null=True, blank=True)
    
    # ESTADO
    is_active = models.BooleanField(
        _("activo"),
        default=True,
        db_index=True,
        help_text="Designa si el usuario puede iniciar sesiÃ³n"
    )
    
    # PERMISOS Y ADMINISTRACIÃ“N
    # is_staff DEBE definirse explÃ­citamente aquÃ­: PermissionsMixin NO lo proporciona.
    # Solo hereda is_superuser, groups y user_permissions.
    # Sin esta definiciÃ³n explÃ­cita, el campo no existirÃ­a en BD y el manager/admin serÃ­a inconsistente.
    is_staff = models.BooleanField(
        _("staff"),
        default=False,
        db_index=True,
        help_text="Designa si el usuario puede acceder al panel admin de Django"
    )
    
    # PREFERENCIAS DE NOTIFICACIÃ“N
    noti_email = models.BooleanField(
        _("notificaciÃ³n por email"),
        default=True,
        help_text="Indica si el usuario desea recibir notificaciones por email"
    )
    noti_push = models.BooleanField(
        _("notificaciÃ³n push"),
        default=True,
        help_text="Indica si el usuario desea recibir notificaciones push"
    )
    
    # AUTENTICACIÃ“N - SESIONES
    session_revoked_at = models.DateTimeField(
        _("sesiÃ³n revocada en"),
        null=True,
        blank=True,
        db_index=True,
        help_text="Si estÃ¡ seteado, todos los tokens emitidos antes de esta fecha son invÃ¡lidos"
    )
    
    # AUDITORÃA
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado en"), auto_now=True)
    
    # AbstractBaseUser proporciona:
    # - password (hasheado automÃ¡ticamente)
    # - last_login (se actualiza automÃ¡ticamente)
    # PermissionsMixin proporciona:
    # - is_superuser, groups, user_permissions
    # Usuario define explÃ­citamente:
    # - is_staff (claridad + control + migraciÃ³n explÃ­cita)

    # MANAGER
    objects = UsuarioManager()
    
    # CONFIGURACIÃ“N DE AUTENTICACIÃ“N DJANGO
    # Multi-tenant: email no es Ãºnico globalmente, es Ãºnico por (empresa, email)
    # USERNAME_FIELD se usa solo en contextos no-tenant (admin Django)
    # En login tenant, bÃºsqueda se hace por (empresa, email) en serializers
    USERNAME_FIELD = "id"  # Usar id como USERNAME_FIELD (Ãºnico globalmente) 
    REQUIRED_FIELDS = []  # No requerimos campos adicionales en creaciÃ³n

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
    SuscripciÃ³n activa de una empresa a un plan.
    Controla quÃ© plan tiene la empresa y cuÃ¡ndo vence.
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
        verbose_name=_("renovaciÃ³n de"),
        help_text="Si es renovaciÃ³n, referencia a la suscripciÃ³n anterior"
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
        help_text="Plan que se aplicarÃ¡ despuÃ©s de terminar el perÃ­odo actual"
    )
    fecha_aplicacion_plan_pendiente = models.DateTimeField(
        _("fecha de aplicaciÃ³n del plan pendiente"),
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
            "Cuando se aplica el plan_pendiente automÃ¡ticamente, este campo se limpia (SET_NULL). "
            "Un solo pago confirmado puede estar vinculado a la vez."
        )
    )
    notas = models.CharField(
        _("notas"),
        max_length=500,
        null=True,
        blank=True,
        help_text="Notas internas sobre la suscripciÃ³n"
    )
    created_at = models.DateTimeField(_("creado en"), auto_now_add=True)

    class Meta:
        db_table = "suscripciones"
        ordering = ["-created_at"]
        verbose_name = _("SuscripciÃ³n")
        verbose_name_plural = _("Suscripciones")
        indexes = [
            models.Index(fields=["empresa", "estado"]),
        ]

    def __str__(self):
        return f"{self.empresa.nombre} - {self.plan.nombre} ({self.estado})"


class Auditoria(models.Model):
    """
    Log de auditorÃ­a de todas las acciones importantes.
    CrÃ­tico para compliance y debugging.
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
        _("acciÃ³n"),
        max_length=100,
        db_index=True,
        help_text="Tipo de acciÃ³n (crear, actualizar, eliminar, login, etc)"
    )
    entidad_tipo = models.CharField(
        _("tipo de entidad"),
        max_length=100,
        null=True,
        blank=True,
        help_text="Modelo sobre el que se actuÃ³ (Usuario, Empresa, etc)"
    )
    entidad_id = models.UUIDField(
        _("ID de entidad"),
        null=True,
        blank=True,
        help_text="UUID de la entidad modificada"
    )
    descripcion = models.CharField(
        _("descripciÃ³n"),
        max_length=500,
        null=True,
        blank=True,
        help_text="DescripciÃ³n legible de la acciÃ³n"
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
        help_text="IP desde donde se realizÃ³ la acciÃ³n"
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
        verbose_name = _("AuditorÃ­a")
        verbose_name_plural = _("AuditorÃ­as")
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



class Pago(models.Model):
    """
    Modelo para registrar pagos con Stripe.
    Se usa al registrar nuevas empresas para cobrar la suscripciÃ³n inicial.
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
        help_text="Password sin hashar (se hashearÃ¡ al crear el usuario)"
    )
    
    # Plan seleccionado
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="pagos",
        verbose_name=_("plan"),
    )
    
    # InformaciÃ³n del pago
    amount_centavos = models.IntegerField(
        _("monto (centavos)"),
        help_text="Monto en centavos"
    )
    moneda = models.CharField(
        _("moneda"),
        max_length=3,
        default="USD",
        help_text="CÃ³digo de moneda ISO (USD, EUR, CLP)"
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
    
    # Empresa creada (si estÃ¡ completado)
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
        help_text="CuÃ¡ndo se procesÃ³ el pago exitosamente"
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


