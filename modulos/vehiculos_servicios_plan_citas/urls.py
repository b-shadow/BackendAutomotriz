from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.vehiculos_servicios_plan_citas.viewsets import (
    VehiculosViewSet,
    ServiciosCatalogoViewSet,
    EspaciosTrabajoViewSet,
    PlanesVehiculoViewSet,
    CitasViewSet,
    ReportesViewSet,
)

app_name = "vehiculos_servicios_plan_citas"

router = DefaultRouter()
router.register(r"vehiculos", VehiculosViewSet, basename="vehiculo")
router.register(r"servicios", ServiciosCatalogoViewSet, basename="servicio-catalogo")
router.register(r"espacios", EspaciosTrabajoViewSet, basename="espacio-trabajo")
router.register(r"planes-vehiculo", PlanesVehiculoViewSet, basename="plan-vehiculo")
router.register(r"citas", CitasViewSet, basename="cita")
router.register(r"reportes", ReportesViewSet, basename="reportes")

urlpatterns = [
    path("", include(router.urls)),
]
