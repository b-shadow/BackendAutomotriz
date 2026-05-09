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

__all__ = [
    "CategoriaInventarioViewSet",
    "ItemInventarioViewSet",
    "MovimientoInventarioViewSet",
    "SolicitudRepuestoViewSet",
]
