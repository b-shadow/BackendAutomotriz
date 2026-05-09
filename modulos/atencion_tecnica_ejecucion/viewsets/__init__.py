"""
Punto de entrada modular para atencion tecnica/ejecucion.
"""

from modulos.atencion_tecnica_ejecucion.viewsets.recepciones import RecepcionVehiculoViewSet
from modulos.atencion_tecnica_ejecucion.viewsets.presupuestos import PresupuestoCitaViewSet
from modulos.atencion_tecnica_ejecucion.viewsets.ordenes_trabajo import OrdenTrabajoViewSet
from modulos.atencion_tecnica_ejecucion.viewsets.avance_taller import AvanceTallerViewSet
from modulos.atencion_tecnica_ejecucion.viewsets.avances_vehiculo import AvanceVehiculoViewSet

__all__ = [
    "RecepcionVehiculoViewSet",
    "PresupuestoCitaViewSet",
    "OrdenTrabajoViewSet",
    "AvanceTallerViewSet",
    "AvanceVehiculoViewSet",
]
