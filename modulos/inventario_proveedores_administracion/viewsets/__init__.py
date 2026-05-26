"""
Punto de entrada modular para inventario/proveedores/administracion.

Sin viewsets activos aun en esta fase.
"""

__all__ = []
from modulos.inventario_proveedores_administracion.viewsets.inventario import (
    CategoriaInventarioViewSet,
    ItemInventarioViewSet,
    MovimientoInventarioViewSet,
    SolicitudRepuestoViewSet,
)
from modulos.inventario_proveedores_administracion.viewsets.administrativo import (
    ProveedorViewSet,
    CompraViewSet,
    VentaMostradorViewSet,
    PagoTallerViewSet,
    FacturaViewSet,
    CajaUsuarioViewSet,
    MovimientoCajaViewSet,
)

__all__ = [
    "CategoriaInventarioViewSet",
    "ItemInventarioViewSet",
    "MovimientoInventarioViewSet",
    "SolicitudRepuestoViewSet",
    "ProveedorViewSet",
    "CompraViewSet",
    "VentaMostradorViewSet",
    "PagoTallerViewSet",
    "FacturaViewSet",
    "CajaUsuarioViewSet",
    "MovimientoCajaViewSet",
]
