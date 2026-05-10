"""
Punto de entrada modular para rutas de comunicacion/control/inteligencia.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.comunicacion_control_inteligencia.viewsets.ia_viewsets import IAViewSet
from modulos.comunicacion_control_inteligencia.viewsets.backups import BackupEmpresaViewSet

router = DefaultRouter()
router.register(r'ia', IAViewSet, basename='ia-assistant')
router.register(r'backups', BackupEmpresaViewSet, basename='backups-empresa')

urlpatterns = [
    path('', include(router.urls)),
]
