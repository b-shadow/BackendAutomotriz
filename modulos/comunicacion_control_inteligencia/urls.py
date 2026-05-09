"""
Punto de entrada modular para rutas de comunicacion/control/inteligencia.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.comunicacion_control_inteligencia.viewsets import BackupEmpresaViewSet
from modulos.comunicacion_control_inteligencia.viewsets.ia_viewsets import IAViewSet

router = DefaultRouter()
router.register(r'ia', IAViewSet, basename='ia-assistant')
router.register(r'backups', BackupEmpresaViewSet, basename='backup-empresa')

urlpatterns = [
    path('', include(router.urls)),
]