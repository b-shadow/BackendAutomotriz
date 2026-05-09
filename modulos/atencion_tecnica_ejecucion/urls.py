from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.atencion_tecnica_ejecucion.viewsets import (
    RecepcionVehiculoViewSet,
    PresupuestoCitaViewSet,
    OrdenTrabajoViewSet,
    AvanceTallerViewSet,
    AvanceVehiculoViewSet,
)

app_name = "atencion_tecnica_ejecucion"

router = DefaultRouter()
router.register(r"recepciones-vehiculo", RecepcionVehiculoViewSet, basename="recepcion-vehiculo")
router.register(r"presupuestos-cita", PresupuestoCitaViewSet, basename="presupuesto-cita")
router.register(r"ordenes-trabajo", OrdenTrabajoViewSet, basename="orden-trabajo")
router.register(r"taller-interno", AvanceTallerViewSet, basename="taller-interno")
router.register(r"avances-vehiculo", AvanceVehiculoViewSet, basename="avances-vehiculo")

urlpatterns = [
    path("", include(router.urls)),
]
