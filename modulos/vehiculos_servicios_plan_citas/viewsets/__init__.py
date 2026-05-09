"""
Punto de entrada modular para viewsets de vehiculos/servicios/plan/citas.

Compatibilidad temporal reutilizando implementaciones legacy.
"""

from modulos.vehiculos_servicios_plan_citas.viewsets.vehiculos import VehiculosViewSet
from modulos.vehiculos_servicios_plan_citas.viewsets.servicios import ServiciosCatalogoViewSet
from modulos.vehiculos_servicios_plan_citas.viewsets.espacios import EspaciosTrabajoViewSet
from modulos.vehiculos_servicios_plan_citas.viewsets.planes_vehiculo import PlanesVehiculoViewSet
from modulos.vehiculos_servicios_plan_citas.viewsets.citas import CitasViewSet
from modulos.vehiculos_servicios_plan_citas.viewsets.reportes_viewsets import ReportesViewSet

__all__ = [
    "VehiculosViewSet",
    "ServiciosCatalogoViewSet",
    "EspaciosTrabajoViewSet",
    "PlanesVehiculoViewSet",
    "CitasViewSet",
    "ReportesViewSet",
]
