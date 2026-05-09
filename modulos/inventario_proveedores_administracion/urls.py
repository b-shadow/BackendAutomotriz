from django.urls import include, path
from rest_framework.routers import DefaultRouter

from modulos.inventario_proveedores_administracion.viewsets import (
    CategoriaInventarioViewSet,
    ItemInventarioViewSet,
    MovimientoInventarioViewSet,
    SolicitudRepuestoViewSet,
)

router = DefaultRouter()
router.register(r"categorias-inventario", CategoriaInventarioViewSet, basename="categoria-inventario")
router.register(r"items-inventario", ItemInventarioViewSet, basename="item-inventario")
router.register(r"movimientos-inventario", MovimientoInventarioViewSet, basename="movimiento-inventario")
router.register(r"solicitudes-repuesto", SolicitudRepuestoViewSet, basename="solicitud-repuesto")

urlpatterns = [
    path("", include(router.urls)),
]
