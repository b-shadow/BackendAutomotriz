"""ViewSet para Auditoría multi-tenant.
Permite a administradores (rol exacto: ADMIN) consultar bitácora de su empresa.
Aislamiento multi-tenant garantizado en get_queryset()."""
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import OrderingFilter, SearchFilter
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

from app.models import Auditoria
from app.serializers import AuditoriaSerializer
from nucleo.permisos import IsCompanyAdmin
from nucleo.paginacion import PaginacionEstandar

class AuditoriaViewSet(viewsets.ReadOnlyModelViewSet):
    """ ViewSet para consultar eventos de auditoría de la empresa del usuario.
    ENDPOINTS:
    - GET /api/{empresa_slug}/auditoria/           - Listar eventos (paginado)
    - GET /api/{empresa_slug}/auditoria/{id}/      - Detalle de evento
    - GET /api/{empresa_slug}/auditoria/resumen/   - Resumen de eventos 
    PERMISOS:
    - IsAuthenticated:  Usuario debe estar autenticado
    - IsCompanyAdmin:   Usuario debe tener rol exacto ADMIN de su empresa
    - get_queryset:     Garantiza aislamiento multi-tenant """
    serializer_class = AuditoriaSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdmin]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    pagination_class = PaginacionEstandar
    
    # Filtros simples que se pueden usar directamente
    filterset_fields = {
        'usuario': ['exact'],
        'accion': ['exact', 'icontains'],
        'entidad_tipo': ['exact', 'icontains'],
        'created_at': ['gte', 'lte', 'gt', 'lt', 'date'],
    }
    
    # Búsqueda en múltiples campos
    search_fields = [
        'descripcion',
        'accion',
        'usuario__nombres',
        'usuario__apellidos',
        'usuario__email',
        'entidad_tipo',
    ]
    
    # Ordenamiento
    ordering_fields = ['created_at', 'accion', 'usuario__email']
    ordering = ['-created_at']

    def get_queryset(self):
        """ AISLAMIENTO MULTI-TENANT: cada usuario solo ve auditoría de su empresa.
        - Si no autenticado: queryset vacío (el permiso lo bloqueará de todas formas)
        - Si autenticado: solo auditoría de request.user.empresa. """
        if not self.request.user or not self.request.user.is_authenticated:
            return Auditoria.objects.none()
        
        # Filtrar por la empresa del usuario autenticado
        # El usuario siempre pertenece exactamente a una empresa
        return Auditoria.objects.filter(
            empresa=self.request.user.empresa
        ).select_related('usuario', 'empresa').prefetch_related('usuario')

    @action(detail=False, methods=['get'])
    def resumen(self, request, empresa_slug=None, *args, **kwargs):
        """ GET /api/{empresa_slug}/auditoria/resumen/. """
        queryset = self.get_queryset()
        # Todos los eventos
        total = queryset.count()
        # Eventos de hoy
        ahora = timezone.now()
        inicio_hoy = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        fin_hoy = inicio_hoy + timedelta(days=1)
        eventos_hoy = queryset.filter(created_at__gte=inicio_hoy, created_at__lt=fin_hoy).count()
        # Eventos de la última semana
        hace_una_semana = timezone.now() - timedelta(days=7)
        eventos_ultima_semana = queryset.filter(created_at__gte=hace_una_semana).count()
        # Frecuencia por acción (top 10)
        acciones_frecuentes = (
            queryset
            .values('accion')
            .annotate(cantidad=Count('id'))
            .order_by('-cantidad')[:10]
        )
        # Usuarios activos en la auditoría
        usuarios_activos = queryset.values('usuario').distinct().count()
        return Response({
            "total_eventos": total,
            "eventos_hoy": eventos_hoy,
            "eventos_ultima_semana": eventos_ultima_semana,
            "acciones_frecuentes": list(acciones_frecuentes),
            "usuarios_activos": usuarios_activos,
        }, status=status.HTTP_200_OK)
