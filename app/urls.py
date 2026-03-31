"""
URLs del API SaaS multi-tenant.

Patrón de tenant (dinámico por empresa): /api/{empresa_slug}/endpoint/
Patrón de sistema (global): /api/endpoint/

Ejemplos:
- /api/empresa-demo/usuarios/
- /api/empresa-demo/usuarios/login/
- /api/empresa-demo/suscripciones/actual/
- /api/empresa-demo/servicios/
- /api/empresa-demo/espacios/
- /api/empresa-demo/planes-vehiculo/
- /api/empresas/
- /api/planes/
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from app.viewsets import (
    UsuariosViewSet,
    PlanViewSet,
    SuscripcionViewSet,
    AuditoriaViewSet,
    VehiculosViewSet,
    ServiciosCatalogoViewSet,
    EspaciosTrabajoViewSet,
    PlanesVehiculoViewSet,
    CitasViewSet,
)

app_name = 'app'

# ============================================================================
# ROUTER PARA ENDPOINTS TENANT (dentro de /api/{empresa_slug}/)
# ============================================================================
tenant_router = DefaultRouter()
tenant_router.register(r"usuarios", UsuariosViewSet, basename="gestion-usuarios")
tenant_router.register(r"suscripciones", SuscripcionViewSet, basename="suscripcion")
tenant_router.register(r"auditoria", AuditoriaViewSet, basename="auditoria")
tenant_router.register(r"vehiculos", VehiculosViewSet, basename="vehiculo")
tenant_router.register(r"servicios", ServiciosCatalogoViewSet, basename="servicio-catalogo")
tenant_router.register(r"espacios", EspaciosTrabajoViewSet, basename="espacio-trabajo")
tenant_router.register(r"planes-vehiculo", PlanesVehiculoViewSet, basename="plan-vehiculo")
tenant_router.register(r"citas", CitasViewSet, basename="cita")

# ============================================================================
# RUTAS EXPLÍCITAS - Endpoints especiales
# ============================================================================
urlpatterns = [
    # Rutas tenant (dinámicas por empresa en config.urls)
    path("", include(tenant_router.urls)),
]
