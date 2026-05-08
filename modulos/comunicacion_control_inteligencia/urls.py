"""
Punto de entrada modular para rutas de comunicacion/control/inteligencia.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from modulos.comunicacion_control_inteligencia.viewsets import BackupEmpresaViewSet

router = DefaultRouter()
router.register(r"backups", BackupEmpresaViewSet, basename="backup-empresa")

urlpatterns = [
    path("", include(router.urls)),
]
