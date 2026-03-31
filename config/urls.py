"""
URLs raíz del proyecto SaaS Backend.

Estructura de rutas:
- /api/tenants/resolve/ - Resolver tenant por slug (global)
- /api/tenants/{slug}/auth/register/ - Registro de usuario por tenant
- /api/tenants/{slug}/auth/login/ - Login de usuario por tenant
- /api/pagos/ - Pagos con Stripe (global)
- /api/empresas/ - Gestionar empresas (global, requiere admin)
- /api/planes/ - Ver planes disponibles (global)
- /api/{empresa_slug}/usuarios/ - Gestionar usuarios (tenant)
- /api/{empresa_slug}/roles/ - Ver roles (tenant)
- /api/{empresa_slug}/suscripciones/ - Gestionar suscripciones (tenant)

NOTA: admin_login fue eliminado. Los admins del SaaS se manejan como Usuarios
con rol ADMIN en una empresa designada o mediante el panel admin de Django.
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)
from app.viewsets import EmpresaViewSet, PlanViewSet
from app.viewsets.pagos import PagoViewSet
from app.viewsets.tenant_auth import (
    resolve_tenant,
    tenant_register,
    tenant_login,
    tenant_logout,
)

# Router para endpoints globales
global_router = DefaultRouter()
global_router.register(r"pagos", PagoViewSet, basename="pago")
global_router.register(r"empresas", EmpresaViewSet, basename="empresa")
global_router.register(r"planes", PlanViewSet, basename="plan")

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),
    
    # API Documentation
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    
    # ========== AUTENTICACIÓN MULTI-TENANT ==========
    # Resolver tenant por slug
    path("api/tenants/resolve/", resolve_tenant, name="resolve_tenant"),
    
    # Auth por tenant (registro, login y logout)
    path(
        "api/tenants/<slug:tenant_slug>/auth/register/",
        tenant_register,
        name="tenant_register"
    ),
    path(
        "api/tenants/<slug:tenant_slug>/auth/login/",
        tenant_login,
        name="tenant_login"
    ),
    path(
        "api/tenants/<slug:tenant_slug>/auth/logout/",
        tenant_logout,
        name="tenant_logout"
    ),
    
    # ========== ENDPOINTS GLOBALES ==========
    # Endpoints globales (no requieren tenant)
    path("api/", include(global_router.urls)),
    
    # ========== ENDPOINTS POR TENANT ==========
    # Rutas dinámicas por tenant: /api/<empresa_slug>/usuarios/, etc
    # Ejemplo: /api/empresa-demo/usuarios/
    path("api/<slug:empresa_slug>/", include("app.urls")),
]

# Static & Media files (solo en desarrollo)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Configurar admin site
admin.site.site_header = "SaaS Backend Admin"
admin.site.site_title = "Admin SaaS"
admin.site.index_title = "Bienvenido"
