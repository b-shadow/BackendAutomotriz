"""
Punto de entrada modular para viewsets de administracion/acceso/configuracion.

En esta fase se mantiene compatibilidad reutilizando implementaciones legacy
de `app.viewsets` hasta completar la migracion fisica de archivos.
"""

from modulos.administracion_acceso_configuracion.viewsets.admin import EmpresaViewSet
from modulos.administracion_acceso_configuracion.viewsets.planes import PlanViewSet
from modulos.administracion_acceso_configuracion.viewsets.pagos import PagoViewSet
from modulos.administracion_acceso_configuracion.viewsets.tenant_auth import (
    resolve_tenant,
    tenant_register,
    tenant_login,
    tenant_logout,
)
from modulos.administracion_acceso_configuracion.viewsets.usuarios import UsuariosViewSet
from modulos.administracion_acceso_configuracion.viewsets.suscripciones import SuscripcionViewSet
from modulos.administracion_acceso_configuracion.viewsets.auditoria import AuditoriaViewSet

__all__ = [
    "EmpresaViewSet",
    "PlanViewSet",
    "PagoViewSet",
    "resolve_tenant",
    "tenant_register",
    "tenant_login",
    "tenant_logout",
    "UsuariosViewSet",
    "SuscripcionViewSet",
    "AuditoriaViewSet",
]
