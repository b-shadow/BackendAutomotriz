"""
Punto de entrada modular para rutas de comunicacion/control/inteligencia.
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.comunicacion_control_inteligencia.viewsets.ia_viewsets import IAViewSet
from modulos.comunicacion_control_inteligencia.viewsets.backups import BackupEmpresaViewSet
from modulos.comunicacion_control_inteligencia.viewsets.notificaciones import NotificacionViewSet
from modulos.comunicacion_control_inteligencia.viewsets.reportes import ReportesViewSet
from modulos.comunicacion_control_inteligencia.viewsets.reportes_ia_viewsets import ReportesIAViewSet

router = DefaultRouter()
router.register(r'ia', IAViewSet, basename='ia-assistant')
router.register(r'backups', BackupEmpresaViewSet, basename='backups-empresa')
router.register(r'notificaciones', NotificacionViewSet, basename='notificaciones')
router.register(r'reportes', ReportesViewSet, basename='reportes')
router.register(r'reportes-ia', ReportesIAViewSet, basename='reportes-ia')

urlpatterns = [
    path('', include(router.urls)),
]
