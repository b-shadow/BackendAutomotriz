from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.administracion_acceso_configuracion.viewsets import (
    UsuariosViewSet,
    SuscripcionViewSet,
    AuditoriaViewSet,
)

app_name = "administracion_acceso_configuracion"

router = DefaultRouter()
router.register(r"usuarios", UsuariosViewSet, basename="gestion-usuarios")
router.register(r"suscripciones", SuscripcionViewSet, basename="suscripcion")
router.register(r"auditoria", AuditoriaViewSet, basename="auditoria")

urlpatterns = [
    path("", include(router.urls)),
]
