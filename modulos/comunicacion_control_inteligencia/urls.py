"""
Punto de entrada modular para rutas de comunicacion/control/inteligencia.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.comunicacion_control_inteligencia.viewsets.ia_viewsets import IAViewSet
from modulos.comunicacion_control_inteligencia.viewsets.backups import BackupEmpresaViewSet
from modulos.comunicacion_control_inteligencia.viewsets.reportes import ReportesViewSet

router = DefaultRouter()
router.register(r'ia', IAViewSet, basename='ia-assistant')
router.register(r'backups', BackupEmpresaViewSet, basename='backups-empresa')
router.register(r'reportes', ReportesViewSet, basename='reportes')

urlpatterns = [
    path('', include(router.urls)),
]
