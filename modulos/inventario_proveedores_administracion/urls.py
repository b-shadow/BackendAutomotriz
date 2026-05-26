from django.urls import include, path
from rest_framework.routers import DefaultRouter

from modulos.inventario_proveedores_administracion.viewsets import (
    CategoriaInventarioViewSet,
    CompraViewSet,
    CajaUsuarioViewSet,
    FacturaViewSet,
    ItemInventarioViewSet,
    MovimientoInventarioViewSet,
    MovimientoCajaViewSet,
    PagoTallerViewSet,
    ProveedorViewSet,
    SolicitudRepuestoViewSet,
    VentaMostradorViewSet,
)

router = DefaultRouter()
router.register(r"categorias-inventario", CategoriaInventarioViewSet, basename="categoria-inventario")
router.register(r"items-inventario", ItemInventarioViewSet, basename="item-inventario")
router.register(r"movimientos-inventario", MovimientoInventarioViewSet, basename="movimiento-inventario")
router.register(r"solicitudes-repuesto", SolicitudRepuestoViewSet, basename="solicitud-repuesto")
router.register(r"proveedores", ProveedorViewSet, basename="proveedor")
router.register(r"compras", CompraViewSet, basename="compra")
router.register(r"ventas-mostrador", VentaMostradorViewSet, basename="venta-mostrador")
router.register(r"pagos-taller", PagoTallerViewSet, basename="pago-taller")
router.register(r"facturas", FacturaViewSet, basename="factura")
router.register(r"cajas", CajaUsuarioViewSet, basename="caja")
router.register(r"movimientos-caja", MovimientoCajaViewSet, basename="movimiento-caja")

urlpatterns = [
    path("", include(router.urls)),
]
