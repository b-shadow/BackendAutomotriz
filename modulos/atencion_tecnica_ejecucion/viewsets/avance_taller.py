from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modulos.atencion_tecnica_ejecucion.models import (
    OrdenTrabajoGlobal,
    OrdenTrabajoDetalle,
    EstadoOrdenTrabajoGlobal,
    EstadoOrdenTrabajoDetalle,
    AvanceVehiculo,
    TipoAvanceVehiculo,
)
from modulos.atencion_tecnica_ejecucion.serializers.ordenes_trabajo import (
    OrdenTrabajoGlobalSerializer,
    OrdenTrabajoDetalleSerializer,
)


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.user.empresa == request.tenant
        )


class PuedeGestionarTaller(permissions.BasePermission):
    def has_permission(self, request, view):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        return rol in ["ADMIN", "ASESOR DE SERVICIO", "MECANICO", "MECÁNICO"]


class AvanceTallerViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = OrdenTrabajoGlobalSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarTaller]

    def get_queryset(self):
        qs = OrdenTrabajoGlobal.objects.filter(
            empresa=self.request.tenant,
            estado__in=[
                EstadoOrdenTrabajoGlobal.ABIERTA,
                EstadoOrdenTrabajoGlobal.ASIGNADA,
                EstadoOrdenTrabajoGlobal.EN_PROCESO,
                EstadoOrdenTrabajoGlobal.PAUSADA,
            ],
        ).prefetch_related("detalles", "mecanicos_asignados")

        rol = self.request.user.rol.nombre if self.request.user and self.request.user.rol else None
        if rol in ["MECANICO", "MECÁNICO"]:
            qs = qs.filter(detalles__mecanico_asignado=self.request.user).distinct()
        return qs.order_by("-fecha_apertura")

    def _validar_permiso_detalle(self, request, detalle):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        if rol in ["ADMIN", "ASESOR DE SERVICIO"]:
            return True
        return detalle.mecanico_asignado_id == request.user.id

    def _validar_orden_editable(self, detalle):
        if detalle.orden_global.estado in [EstadoOrdenTrabajoGlobal.CERRADA, EstadoOrdenTrabajoGlobal.CANCELADA]:
            raise ValueError("No se puede modificar una orden cerrada o cancelada.")

    def _calcular_porcentaje_orden(self, orden):
        total = orden.detalles.count()
        if total <= 0:
            return 0
        resueltos = orden.detalles.filter(estado__in=[EstadoOrdenTrabajoDetalle.FINALIZADO, EstadoOrdenTrabajoDetalle.INNECESARIO]).count()
        return int(round((resueltos * 100) / total))

    def _registrar_avance(self, request, detalle, estado, mensaje, porcentaje=None):
        if porcentaje is None:
            porcentaje = self._calcular_porcentaje_orden(detalle.orden_global)
        AvanceVehiculo.objects.create(
            empresa=request.tenant,
            cita=detalle.orden_global.cita,
            orden_detalle=detalle,
            registrado_por=request.user,
            tipo=TipoAvanceVehiculo.SERVICIO,
            estado_nuevo=estado,
            mensaje=mensaje,
            porcentaje_avance=porcentaje,
            visible_cliente=True,
        )

    @action(detail=True, methods=["post"], url_path="iniciar-detalle")
    @transaction.atomic
    def iniciar_detalle(self, request, pk=None, **kwargs):
        detalle_id = request.data.get("detalle_id")
        try:
            detalle = OrdenTrabajoDetalle.objects.select_related("orden_global").get(
                id=detalle_id, orden_global_id=pk, empresa=request.tenant
            )
        except OrdenTrabajoDetalle.DoesNotExist:
            return Response({"error": "Detalle no encontrado."}, status=status.HTTP_404_NOT_FOUND)

        if not self._validar_permiso_detalle(request, detalle):
            return Response({"error": "No autorizado para actualizar este detalle."}, status=status.HTTP_403_FORBIDDEN)
        try:
            self._validar_orden_editable(detalle)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if detalle.estado not in [EstadoOrdenTrabajoDetalle.POR_HACER, EstadoOrdenTrabajoDetalle.PAUSADO]:
            return Response({"error": "Transicion no permitida para iniciar este detalle."}, status=status.HTTP_400_BAD_REQUEST)

        detalle.estado = EstadoOrdenTrabajoDetalle.EN_PROCESO
        if not detalle.inicio_real:
            detalle.inicio_real = timezone.now()
        detalle.save(update_fields=["estado", "inicio_real", "updated_at"])
        self._registrar_avance(
            request,
            detalle,
            "EN PROCESO",
            f"Se inició el servicio: {detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else 'Servicio'}.",
        )
        return Response(OrdenTrabajoDetalleSerializer(detalle).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="pausar-detalle")
    @transaction.atomic
    def pausar_detalle(self, request, pk=None, **kwargs):
        detalle_id = request.data.get("detalle_id")
        motivo = request.data.get("motivo", "")
        try:
            detalle = OrdenTrabajoDetalle.objects.select_related("orden_global").get(
                id=detalle_id, orden_global_id=pk, empresa=request.tenant
            )
        except OrdenTrabajoDetalle.DoesNotExist:
            return Response({"error": "Detalle no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if not self._validar_permiso_detalle(request, detalle):
            return Response({"error": "No autorizado para actualizar este detalle."}, status=status.HTTP_403_FORBIDDEN)
        try:
            self._validar_orden_editable(detalle)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if detalle.estado != EstadoOrdenTrabajoDetalle.EN_PROCESO:
            return Response({"error": "Solo se puede pausar un detalle en proceso."}, status=status.HTTP_400_BAD_REQUEST)
        detalle.estado = EstadoOrdenTrabajoDetalle.PAUSADO
        if motivo:
            detalle.observaciones_mecanico = (detalle.observaciones_mecanico or "") + f"\n[PAUSA] {motivo}"
        detalle.save(update_fields=["estado", "observaciones_mecanico", "updated_at"])
        self._registrar_avance(
            request,
            detalle,
            "PAUSADO",
            f"Servicio pausado: {motivo or 'en revisión'}",
        )
        return Response(OrdenTrabajoDetalleSerializer(detalle).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="finalizar-detalle")
    @transaction.atomic
    def finalizar_detalle(self, request, pk=None, **kwargs):
        detalle_id = request.data.get("detalle_id")
        tiempo_real_min = request.data.get("tiempo_real_min")
        obs = request.data.get("observaciones_mecanico", "")
        try:
            detalle = OrdenTrabajoDetalle.objects.select_related("orden_global").get(
                id=detalle_id, orden_global_id=pk, empresa=request.tenant
            )
        except OrdenTrabajoDetalle.DoesNotExist:
            return Response({"error": "Detalle no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if not self._validar_permiso_detalle(request, detalle):
            return Response({"error": "No autorizado para actualizar este detalle."}, status=status.HTTP_403_FORBIDDEN)
        try:
            self._validar_orden_editable(detalle)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if detalle.estado not in [EstadoOrdenTrabajoDetalle.EN_PROCESO, EstadoOrdenTrabajoDetalle.PAUSADO]:
            return Response({"error": "No se puede finalizar un detalle no iniciado."}, status=status.HTTP_400_BAD_REQUEST)
        if tiempo_real_min is not None and int(tiempo_real_min) < 0:
            return Response({"error": "Tiempo real invalido."}, status=status.HTTP_400_BAD_REQUEST)

        detalle.estado = EstadoOrdenTrabajoDetalle.FINALIZADO
        detalle.fin_real = timezone.now()
        if tiempo_real_min is not None:
            detalle.tiempo_real_min = int(tiempo_real_min)
        if obs:
            detalle.observaciones_mecanico = obs
        detalle.save(update_fields=["estado", "fin_real", "tiempo_real_min", "observaciones_mecanico", "updated_at"])
        self._registrar_avance(
            request,
            detalle,
            "FINALIZADO",
            f"Servicio finalizado: {detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else 'Servicio'}.",
        )
        return Response(OrdenTrabajoDetalleSerializer(detalle).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="marcar-innecesario")
    @transaction.atomic
    def marcar_innecesario(self, request, pk=None, **kwargs):
        detalle_id = request.data.get("detalle_id")
        motivo = request.data.get("motivo", "")
        try:
            detalle = OrdenTrabajoDetalle.objects.select_related("orden_global").get(
                id=detalle_id, orden_global_id=pk, empresa=request.tenant
            )
        except OrdenTrabajoDetalle.DoesNotExist:
            return Response({"error": "Detalle no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        if not self._validar_permiso_detalle(request, detalle):
            return Response({"error": "No autorizado para actualizar este detalle."}, status=status.HTTP_403_FORBIDDEN)
        try:
            self._validar_orden_editable(detalle)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        detalle.estado = EstadoOrdenTrabajoDetalle.INNECESARIO
        if motivo:
            detalle.observaciones_mecanico = (detalle.observaciones_mecanico or "") + f"\n[INNECESARIO] {motivo}"
        detalle.save(update_fields=["estado", "observaciones_mecanico", "updated_at"])
        self._registrar_avance(
            request,
            detalle,
            "INNECESARIO",
            f"Servicio marcado como no necesario: {motivo or 'sin motivo especificado'}.",
        )
        return Response(OrdenTrabajoDetalleSerializer(detalle).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="finalizar-orden")
    @transaction.atomic
    def finalizar_orden(self, request, pk=None, **kwargs):
        orden = self.get_object()
        if orden.estado in [EstadoOrdenTrabajoGlobal.CERRADA, EstadoOrdenTrabajoGlobal.CANCELADA]:
            return Response({"error": "Orden no editable."}, status=status.HTTP_400_BAD_REQUEST)
        pendientes = orden.detalles.exclude(
            estado__in=[EstadoOrdenTrabajoDetalle.FINALIZADO, EstadoOrdenTrabajoDetalle.INNECESARIO]
        ).exists()
        if pendientes:
            return Response({"error": "Aun hay detalles pendientes de cierre."}, status=status.HTTP_400_BAD_REQUEST)
        orden.estado = EstadoOrdenTrabajoGlobal.FINALIZADA
        orden.fecha_cierre = timezone.now()
        orden.save(update_fields=["estado", "fecha_cierre", "updated_at"])
        return Response(OrdenTrabajoGlobalSerializer(orden).data, status=status.HTTP_200_OK)


