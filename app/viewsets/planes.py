""" ViewSet para gestionar Planes de suscripción."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from app.models import Plan
from app.serializers import PlanSerializer

class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    """ ViewSet para consultar el catálogo de planes de suscripción (solo lectura).
    - GET /api/planes/              # Catálogo completo (AllowAny)
    - GET /api/planes/{id}/         # Detalle de un plan (AllowAny) """
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [AllowAny]
    filterset_fields = ["codigo", "moneda"]
    search_fields = ["nombre", "codigo", "descripcion"]
    ordering_fields = ["precio_centavos", "duracion_dias", "nombre"]
    ordering = ["precio_centavos"]
