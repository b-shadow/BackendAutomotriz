from django.urls import path, include
from rest_framework.routers import DefaultRouter

from modulos.atencion_tecnica_ejecucion.viewsets import RecepcionVehiculoViewSet

app_name = "atencion_tecnica_ejecucion"

router = DefaultRouter()
router.register(r"recepciones-vehiculo", RecepcionVehiculoViewSet, basename="recepcion-vehiculo")

urlpatterns = [
    path("", include(router.urls)),
]
