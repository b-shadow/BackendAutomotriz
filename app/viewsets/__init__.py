"""
Importes centralizados para ViewSets del proyecto SaaS multi-tenant.

IMPORTANTE: Este archivo SOLO contiene imports de ViewSets.
Los ViewSets están implementados en sus módulos específicos para mantener
una estructura clara y evitar duplicación de código.

Módulos de ViewSets:
- app.viewsets.usuarios -> UsuariosViewSet
- app.viewsets.suscripciones -> SuscripcionViewSet, PlanViewSet
- app.viewsets.pagos -> PagoViewSet
- app.viewsets.auditoria -> AuditoriaViewSet
- app.viewsets.admin -> EmpresaViewSet
- app.viewsets.vehiculos -> VehiculosViewSet
- app.viewsets.servicios -> ServiciosCatalogoViewSet
- app.viewsets.espacios -> EspaciosTrabajoViewSet
- app.viewsets.planes_vehiculo -> PlanesVehiculoViewSet
- app.viewsets.citas -> CitasViewSet
"""

from app.viewsets.usuarios import UsuariosViewSet
from app.viewsets.suscripciones import SuscripcionViewSet
from app.viewsets.planes import PlanViewSet
from app.viewsets.pagos import PagoViewSet
from app.viewsets.auditoria import AuditoriaViewSet
from app.viewsets.admin import EmpresaViewSet
from app.viewsets.vehiculos import VehiculosViewSet
from app.viewsets.servicios import ServiciosCatalogoViewSet
from app.viewsets.espacios import EspaciosTrabajoViewSet
from app.viewsets.planes_vehiculo import PlanesVehiculoViewSet
from app.viewsets.citas import CitasViewSet

__all__ = [
    'UsuariosViewSet',
    'SuscripcionViewSet',
    'PlanViewSet',
    'PagoViewSet',
    'AuditoriaViewSet',
    'EmpresaViewSet',
    'VehiculosViewSet',
    'ServiciosCatalogoViewSet',
    'EspaciosTrabajoViewSet',
    'PlanesVehiculoViewSet',
    'CitasViewSet',
]
