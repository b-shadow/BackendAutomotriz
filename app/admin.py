"""
Configuración de Django Admin
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import Empresa, Plan, Rol, Usuario, Suscripcion, Auditoria, Pago


class UsuarioAdmin(BaseUserAdmin):
    """
    Admin personalizado para el modelo Usuario.
    
    Configura visualización y edición de usuarios en el panel admin de Django,
    asegurando que campos como is_staff, is_superuser sean accesibles.
    """
    
    # Campos mostrados en la lista de usuarios
    list_display = (
        "email",
        "nombres",
        "apellidos",
        "empresa",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
    )
    
    # Campos por los que se puede filtrar
    list_filter = (
        "empresa",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
    )
    
    # Campos por los que se puede buscar
    search_fields = ("email", "nombres", "apellidos")
    
    # Ordenamiento por defecto
    ordering = ("-created_at",)
    
    # Agrupación de campos en formulario de edición
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Información personal"),
            {
                "fields": ("nombres", "apellidos", "telefono"),
            },
        ),
        (
            _("Empresa y Rol"),
            {
                "fields": ("empresa", "rol"),
            },
        ),
        (
            _("Permisos y Estado"),
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                "classes": ("collapse",),
            },
        ),
        (
            _("Auditoría"),
            {
                "fields": ("created_at", "updated_at", "last_login"),
                "classes": ("collapse",),
            },
        ),
    )
    
    # Campos en el formulario de adición (creación de usuario)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
        (
            _("Información personal"),
            {
                "classes": ("wide",),
                "fields": ("nombres", "apellidos", "telefono"),
            },
        ),
        (
            _("Empresa y Rol"),
            {
                "classes": ("wide",),
                "fields": ("empresa", "rol"),
            },
        ),
        (
            _("Permisos"),
            {
                "classes": ("wide",),
                "fields": ("is_active", "is_staff", "is_superuser"),
            },
        ),
    )
    
    # Campos solo lectura (no editables)
    readonly_fields = ("created_at", "updated_at", "last_login")
    
    # Campos no editables en la página de cambio
    filter_horizontal = ("groups", "user_permissions")


admin.site.register(Usuario, UsuarioAdmin)
admin.site.register(Empresa)
admin.site.register(Plan)
admin.site.register(Rol)
admin.site.register(Suscripcion)
admin.site.register(Auditoria)
admin.site.register(Pago)
