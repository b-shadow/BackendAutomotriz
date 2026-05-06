"""Modelos del modulo 3.5.5 Comunicacion, Control e Inteligencia."""

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario

PlantillaNotificacion = None
Backup = None
BackupProgramado = None
RestauracionBackup = None
PermisoAccionIA = None
PlantillaReporte = None
ArchivoReporte = None

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
