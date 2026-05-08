from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from modulos.atencion_tecnica_ejecucion.models import (
    OrdenTrabajoGlobal,
    OrdenTrabajoDetalle,
    OrdenTrabajoGlobalMecanico,
    EstadoOrdenTrabajoGlobal,
)
from modulos.atencion_tecnica_ejecucion.serializers.ordenes_trabajo import OrdenTrabajoGlobalSerializer
from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)
from modulos.atencion_tecnica_ejecucion.services.ordenes_trabajo import OrdenTrabajoService


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, 'tenant') or request.user.empresa != request.tenant:
            return False
        return True


class PuedeGestionarOrdenes(permissions.BasePermission):
    def has_permission(self, request, view):
        rol_nombre = request.user.rol.nombre if request.user and request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]


class OrdenTrabajoViewSet(viewsets.ModelViewSet):
    serializer_class = OrdenTrabajoGlobalSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["numero", "cita__vehiculo__placa", "cita__cliente__nombres", "cita__cliente__apellidos"]
    ordering_fields = ["created_at", "fecha_apertura", "estado", "numero"]
    ordering = ["-fecha_apertura"]
    filterset_fields = ["estado", "cita"]

    def get_permissions(self):
        if self.action in ["create", "partial_update", "update", "destroy", "asignar_mecanicos"]:
            return [IsAuthenticatedTenant(), PuedeGestionarOrdenes()]
        return [IsAuthenticatedTenant()]

    def get_queryset(self):
        qs = OrdenTrabajoGlobal.objects.filter(empresa=self.request.tenant).select_related(
            "cita", "cita__vehiculo", "cita__cliente", "asesor_responsable"
        ).prefetch_related("detalles", "mecanicos_asignados", "mecanicos_asignados__mecanico")

        rol_nombre = self.request.user.rol.nombre if self.request.user and self.request.user.rol else None
        if rol_nombre in ["MECANICO", "MECÁNICO"]:
            qs = qs.filter(
                Q(mecanicos_asignados__mecanico=self.request.user) |
                Q(detalles__mecanico_asignado=self.request.user)
            ).distinct()
        elif rol_nombre == "USUARIO":
            qs = qs.filter(cita__cliente=self.request.user)
        return qs

    def _obtener_mecanicos_validos(self, empresa, mecanicos_payload):
        if not mecanicos_payload:
            return []

        mecanicos = []
        principales = 0
        for row in mecanicos_payload:
            mecanico_id = row.get("mecanico_id")
            es_principal = bool(row.get("es_principal", False))
            try:
                mec = Usuario.objects.select_related("rol").get(id=mecanico_id, empresa=empresa, is_active=True)
            except Usuario.DoesNotExist:
                raise ValueError("Mecanico invalido o no pertenece a la empresa.")

            rol_nombre = mec.rol.nombre if mec.rol else ""
            if rol_nombre not in ["MECANICO", "MECÁNICO"]:
                raise ValueError("El usuario asignado no tiene rol tecnico de mecanico.")

            if es_principal:
                principales += 1
            mecanicos.append((mec, es_principal))

        if principales > 1:
            raise ValueError("Solo puede haber un mecanico principal por orden.")

        return mecanicos

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        return Response(
            {"error": "La OT se crea automaticamente al registrar la recepcion. Use este modulo para editar/asignar."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"], url_path="asignar-mecanicos")
    @transaction.atomic
    def asignar_mecanicos(self, request, pk=None, **kwargs):
        orden = self.get_object()
        try:
            mecanicos = self._obtener_mecanicos_validos(request.tenant, request.data.get("mecanicos", []))
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        OrdenTrabajoGlobalMecanico.objects.filter(orden_global=orden, empresa=request.tenant).delete()
        for mec, es_principal in mecanicos:
            OrdenTrabajoGlobalMecanico.objects.create(
                empresa=request.tenant,
                orden_global=orden,
                mecanico=mec,
                es_principal=es_principal,
                asignado_at=timezone.now(),
            )
        if mecanicos and orden.estado == EstadoOrdenTrabajoGlobal.ABIERTA:
            orden.estado = EstadoOrdenTrabajoGlobal.ASIGNADA
            orden.save(update_fields=["estado", "updated_at"])

        return Response(OrdenTrabajoGlobalSerializer(orden).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="asignar-detalles")
    @transaction.atomic
    def asignar_detalles(self, request, pk=None, **kwargs):
        orden = self.get_object()
        asignaciones = request.data.get("detalles", [])
        for item in asignaciones:
            detalle_id = item.get("detalle_id")
            mecanico_id = item.get("mecanico_id")
            try:
                detalle = OrdenTrabajoDetalle.objects.get(id=detalle_id, orden_global=orden, empresa=request.tenant)
            except OrdenTrabajoDetalle.DoesNotExist:
                continue
            if not mecanico_id:
                detalle.mecanico_asignado = None
                detalle.save(update_fields=["mecanico_asignado", "updated_at"])
                continue
            try:
                mec = Usuario.objects.select_related("rol").get(id=mecanico_id, empresa=request.tenant, is_active=True)
            except Usuario.DoesNotExist:
                continue
            rol_nombre = mec.rol.nombre if mec.rol else ""
            if rol_nombre not in ["MECANICO", "MECÁNICO"]:
                continue
            detalle.mecanico_asignado = mec
            detalle.save(update_fields=["mecanico_asignado", "updated_at"])
        return Response(OrdenTrabajoGlobalSerializer(orden).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="iniciar")
    @transaction.atomic
    def iniciar(self, request, pk=None, **kwargs):
        orden = self.get_object()
        tiene_mecanicos = OrdenTrabajoGlobalMecanico.objects.filter(orden_global=orden, empresa=request.tenant).exists()
        if not tiene_mecanicos:
            return Response(
                {"error": "Debe asignar al menos un mecanico para poner en marcha la orden."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        orden.estado = EstadoOrdenTrabajoGlobal.EN_PROCESO
        orden.save(update_fields=["estado", "updated_at"])
        return Response(OrdenTrabajoGlobalSerializer(orden).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="mecanicos-disponibles")
    def mecanicos_disponibles(self, request, **kwargs):
        qs = Usuario.objects.select_related("rol").filter(empresa=request.tenant, is_active=True)
        data = []
        for u in qs:
            rol = u.rol.nombre if u.rol else ""
            if rol in ["MECANICO", "MECÁNICO"]:
                data.append({
                    "id": str(u.id),
                    "nombre": f"{u.nombres} {u.apellidos}".strip(),
                    "email": u.email,
                })
        return Response(data, status=status.HTTP_200_OK)
