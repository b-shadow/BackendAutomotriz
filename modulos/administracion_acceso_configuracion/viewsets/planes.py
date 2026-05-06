""" ViewSet para gestionar Planes de suscripciÃ³n."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from modulos.administracion_acceso_configuracion.models import Plan
from modulos.administracion_acceso_configuracion.serializers import PlanSerializer

class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """ ViewSet para consultar el catÃ¡logo de planes de suscripciÃ³n (solo lectura).
    - GET /api/planes/              # CatÃ¡logo completo (AllowAny)
    - GET /api/planes/{id}/         # Detalle de un plan (AllowAny) """
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["codigo", "moneda"]
    search_fields = ["nombre", "codigo", "descripcion"]
    ordering_fields = ["precio_centavos", "duracion_dias", "nombre"]
    ordering = ["precio_centavos"]

