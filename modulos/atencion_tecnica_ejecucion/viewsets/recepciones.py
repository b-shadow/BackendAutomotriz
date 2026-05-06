"""
ViewSet para gestiÃ³n de Recepciones de VehÃ­culos.
Implementa SP1-T007: Registrar recepciÃ³n e inspecciÃ³n del vehÃ­culo.

Funcionalidades:
- Crear recepciÃ³n de vehÃ­culo (cambia estado de cita a EN_PROCESO)
- Listar recepciones
- Ver detalle de recepciÃ³n
- Editar observaciones de recepciÃ³n
- Listar citas listas para recepciÃ³n (EN_ESPERA_INGRESO)
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction
from django.utils import timezone

from modulos.atencion_tecnica_ejecucion.models import RecepcionVehiculo
from modulos.vehiculos_servicios_plan_citas.models import Cita, EstadoCita
from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.atencion_tecnica_ejecucion.serializers.recepciones import (
    RecepcionVehiculoSerializer,
    RecepcionVehiculoCreacionSerializer,
    RecepcionVehiculoDetalleSerializer,
    RecepcionVehiculoListaSerializer,
    RecepcionVehiculoActualizacionSerializer,
)
from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaListadoSerializer
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    AccionAuditoria,
)


# ============================================================================
# PERMISOS PERSONALIZADOS
# ============================================================================

class IsAuthenticatedTenant(permissions.BasePermission):
    """
    Permite acceso a cualquier usuario autenticado del tenant actual.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        return True


class PuedeGestionarRecepcion(permissions.BasePermission):
    """
    Permite crear y editar recepciones solo a asesor de servicio y admin.
    - ADMIN: puede gestionar todas las recepciones
    - ASESOR DE SERVICIO: puede crear y gestionar todas las recepciones
    - Otros: no permitido
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        
        # Solo ADMIN y ASESOR DE SERVICIO pueden crear/editar recepciones
        if view.action in ["create", "update", "partial_update", "destroy"]:
            return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]
        
        # Otros roles (MECANICO, etc) solo pueden ver
        return True


# ============================================================================
# VIEWSET: RECEPCIÃ“N DE VEHÃCULOS
# ============================================================================

class RecepcionVehiculoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar recepciones de vehÃ­culos.
    
    Permisos:
    - Solo ASESOR_SERVICIO y ADMIN pueden crear recepciones
    - Solo pueden acceder a recepciones de su empresa
    
    Flujo: Cita PROGRAMADA â†’ RecepcionVehiculo creada â†’ Cita cambia a EN_PROCESO â†’ Orden de Trabajo
    
    Endpoints:
    - POST /api/{slug}/recepciones-vehiculo/ - Crear recepciÃ³n
    - GET /api/{slug}/recepciones-vehiculo/ - Listar recepciones
    - GET /api/{slug}/recepciones-vehiculo/{id}/ - Detalle
    - PATCH /api/{slug}/recepciones-vehiculo/{id}/ - Editar
    - GET /api/{slug}/recepciones-vehiculo/citas-pendientes/ - Citas PROGRAMADA para recibir
    """

    queryset = RecepcionVehiculo.objects.all()
    serializer_class = RecepcionVehiculoSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarRecepcion]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ["nivel_combustible", "asesor_registra"]
    search_fields = [
        "cita__vehiculo__placa",
        "cita__vehiculo__propietario__nombres",
    ]
    ordering_fields = ["fecha_recepcion", "created_at"]
    ordering = ["-fecha_recepcion"]

    def get_queryset(self):
        """Filtra recepciones por empresa del usuario."""
        if not self.request.user or not self.request.user.is_authenticated:
            return RecepcionVehiculo.objects.none()

        empresa_id = self.kwargs.get("empresa_id") or getattr(
            self.request, "tenant_id", None
        )
        if not empresa_id:
            return RecepcionVehiculo.objects.none()

        return RecepcionVehiculo.objects.filter(
            empresa_id=empresa_id
        ).select_related(
            "cita",
            "cita__vehiculo",
            "cita__vehiculo__propietario",
            "asesor_registra",
            "empresa",
        )

    def get_serializer_context(self):
        """Agrega empresa_id al contexto."""
        context = super().get_serializer_context()
        empresa_id = self.kwargs.get("empresa_id") or getattr(
            self.request, "tenant_id", None
        )
        context["empresa_id"] = empresa_id
        return context

    def get_serializer_class(self):
        """Elige serializer segÃºn acciÃ³n."""
        if self.action == "create":
            return RecepcionVehiculoCreacionSerializer
        elif self.action == "retrieve":
            return RecepcionVehiculoDetalleSerializer
        elif self.action == "list":
            return RecepcionVehiculoListaSerializer
        elif self.action == "partial_update":
            return RecepcionVehiculoActualizacionSerializer
        return RecepcionVehiculoSerializer

    def check_permissions(self, request):
        """Validar permisos segÃºn acciÃ³n."""
        if self.action in ["create"]:
            # Solo ASESOR_SERVICIO y ADMIN pueden crear recepciones
            rol_nombre = request.user.rol.nombre if request.user.rol else None
            if not (
                rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]
                or request.user.is_staff
            ):
                self.permission_denied(
                    request,
                    message="Solo Asesor de Servicio y Admin pueden registrar recepciones.",
                )
        super().check_permissions(request)

    def perform_create(self, serializer):
        """Crea recepciÃ³n y registra auditorÃ­a."""
        recepcion = serializer.save()

        # Registrar evento de auditorÃ­a
        registrar_evento_desde_request(
            request=self.request,
            empresa=recepcion.empresa,
            accion=AccionAuditoria.RECEPCION_REGISTRADA,
            usuario=self.request.user,
            entidad_tipo="RecepcionVehiculo",
            entidad_id=recepcion.id,
            descripcion=f"RecepciÃ³n de {recepcion.cita.vehiculo.placa if recepcion.cita.vehiculo else 'vehÃ­culo'} registrada - Cita pasÃ³ a EN_PROCESO",
            metadata={
                "cita_id": str(recepcion.cita.id),
                "km_ingreso": recepcion.kilometraje_ingreso,
                "combustible": recepcion.nivel_combustible,
            },
        )

    def perform_update(self, serializer):
        """Actualiza recepciÃ³n y registra auditorÃ­a."""
        recepcion_anterior = self.get_object()
        cambios = {}

        if hasattr(serializer, "initial_data"):
            if "observaciones" in serializer.initial_data:
                cambios["observaciones"] = {
                    "anterior": recepcion_anterior.observaciones,
                    "nuevo": serializer.initial_data["observaciones"],
                }

        recepcion = serializer.save()

        if cambios:
            registrar_evento_desde_request(
                request=self.request,
                empresa=recepcion.empresa,
                accion=AccionAuditoria.RECEPCION_ACTUALIZADA,
                usuario=self.request.user,
                entidad_tipo="RecepcionVehiculo",
                entidad_id=recepcion.id,
                descripcion="RecepciÃ³n de vehÃ­culo actualizada",
                metadata=cambios,
            )

    @action(detail=False, methods=["get"], url_path="citas-pendientes")
    def citas_pendientes(self, request, **kwargs):
        """
        Retorna citas que aÃºn no tienen recepciÃ³n registrada.
        Filtro: estado = PROGRAMADA (listas para recibir)
        
        GET /api/{slug}/recepciones-vehiculo/citas-pendientes/
        """
        empresa_id = getattr(request, "tenant_id", None)

        # Citas en estado PROGRAMADA (listas para recibir)
        citas = Cita.objects.filter(
            empresa_id=empresa_id,
            estado=EstadoCita.PROGRAMADA,
        ).select_related(
            "vehiculo",
            "vehiculo__propietario",
            "plan_servicio",
        ).prefetch_related(
            "detalles",
            "detalles__servicio_catalogo"
        )

        # Excluir citas que ya tienen recepciÃ³n
        citas = citas.exclude(recepcion__isnull=False)

        # Paginar
        page = self.paginate_queryset(citas)
        if page is not None:
            serializer = CitaListadoSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = CitaListadoSerializer(citas, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="cita-info")
    def cita_info(self, request, pk=None, empresa_slug=None, **kwargs):
        """
        Retorna informaciÃ³n completa de la cita asociada a esta recepciÃ³n.
        
        GET /api/{slug}/recepciones-vehiculo/{id}/cita-info/
        """
        recepcion = self.get_object()
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaDetalleSerializer

        serializer = CitaDetalleSerializer(recepcion.cita)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="bulk-list")
    def bulk_list(self, request, **kwargs):
        """
        Retorna mÃºltiples recepciones por IDs.
        
        POST /api/{slug}/recepciones-vehiculo/bulk-list/
        Body: {"ids": ["uuid1", "uuid2", ...]}
        """
        ids = request.data.get("ids", [])
        if not ids:
            return Response(
                {"error": "Se requiere lista de IDs"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        recepciones = self.get_queryset().filter(id__in=ids)

        serializer = RecepcionVehiculoDetalleSerializer(recepciones, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="estadisticas")
    def estadisticas(self, request, **kwargs):
        """
        Retorna estadÃ­sticas de recepciones.
        
        GET /api/{slug}/recepciones-vehiculo/estadisticas/
        """
        recepciones = self.get_queryset()

        total = recepciones.count()
        por_combustible = dict(
            recepciones.values("nivel_combustible").annotate(
                cantidad=__import__("django.db.models", fromlist=["Count"]).Count(
                    "id"
                )
            ).values_list("nivel_combustible", "cantidad")
        )
        por_asesor = dict(
            recepciones.values("asesor_registra__nombres").annotate(
                cantidad=__import__("django.db.models", fromlist=["Count"]).Count(
                    "id"
                )
            ).values_list("asesor_registra__nombres", "cantidad")
        )

        return Response(
            {
                "total": total,
                "por_nivel_combustible": por_combustible,
                "por_asesor": por_asesor,
                "hoy": recepciones.filter(
                    fecha_recepcion__date=timezone.now().date()
                ).count(),
            }
        )

