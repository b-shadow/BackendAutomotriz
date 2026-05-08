from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modulos.inventario_proveedores_administracion.models import (
    CategoriaInventario,
    ItemInventario,
    MovimientoInventario,
    SolicitudRepuesto,
    SolicitudRepuestoDetalle,
    TipoMovimientoInventario,
    EstadoSolicitudRepuesto,
    EstadoSolicitudRepuestoDetalle,
)
from modulos.inventario_proveedores_administracion.serializers.inventario import (
    CategoriaInventarioSerializer,
    ItemInventarioSerializer,
    MovimientoInventarioSerializer,
)
from modulos.inventario_proveedores_administracion.serializers.solicitudes import (
    SolicitudRepuestoSerializer,
)


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.user.empresa == request.tenant
        )


class PuedeGestionarInventario(permissions.BasePermission):
    def has_permission(self, request, view):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        return rol in ["ADMIN", "ALMACENERO", "ASESOR DE SERVICIO"]


class CategoriaInventarioViewSet(viewsets.ModelViewSet):
    serializer_class = CategoriaInventarioSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarInventario]

    def get_queryset(self):
        return CategoriaInventario.objects.filter(empresa=self.request.tenant).order_by("nombre")

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant)


class ItemInventarioViewSet(viewsets.ModelViewSet):
    serializer_class = ItemInventarioSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarInventario]

    def get_queryset(self):
        return ItemInventario.objects.filter(empresa=self.request.tenant).order_by("nombre")

    def perform_create(self, serializer):
        serializer.save(empresa=self.request.tenant)

    @action(detail=True, methods=["post"], url_path="ajustar-stock")
    @transaction.atomic
    def ajustar_stock(self, request, pk=None, **kwargs):
        item = self.get_object()
        tipo = request.data.get("tipo_movimiento")
        cantidad = int(request.data.get("cantidad") or 0)
        observacion = request.data.get("observacion", "")
        referencia_tipo = request.data.get("referencia_tipo")
        referencia_id = request.data.get("referencia_id")

        if cantidad <= 0:
            return Response({"error": "La cantidad debe ser mayor a 0."}, status=status.HTTP_400_BAD_REQUEST)

        stock_anterior = item.stock_actual
        stock_posterior = stock_anterior

        if tipo == TipoMovimientoInventario.ENTRADA_COMPRA:
            stock_posterior = stock_anterior + cantidad
            delta = cantidad
        elif tipo in [TipoMovimientoInventario.SALIDA_TALLER, TipoMovimientoInventario.SALIDA_VENTA]:
            if stock_anterior < cantidad:
                return Response({"error": "Stock insuficiente para la salida solicitada."}, status=status.HTTP_400_BAD_REQUEST)
            stock_posterior = stock_anterior - cantidad
            delta = -cantidad
        elif tipo == TipoMovimientoInventario.AJUSTE:
            # Ajuste positivo/negativo permitido via 'cantidad_ajuste' opcional
            cantidad_ajuste = int(request.data.get("cantidad_ajuste") or 0)
            if cantidad_ajuste == 0:
                return Response({"error": "Para ajuste debe enviar cantidad_ajuste distinto de 0."}, status=status.HTTP_400_BAD_REQUEST)
            if stock_anterior + cantidad_ajuste < 0:
                return Response({"error": "El ajuste dejaria stock negativo."}, status=status.HTTP_400_BAD_REQUEST)
            stock_posterior = stock_anterior + cantidad_ajuste
            delta = cantidad_ajuste
        else:
            return Response({"error": "tipo_movimiento invalido."}, status=status.HTTP_400_BAD_REQUEST)

        item.stock_actual = stock_posterior
        item.save(update_fields=["stock_actual", "updated_at"])

        mov = MovimientoInventario.objects.create(
            empresa=request.tenant,
            item_inventario=item,
            tipo_movimiento=tipo,
            cantidad=delta,
            stock_anterior=stock_anterior,
            stock_posterior=stock_posterior,
            referencia_tipo=referencia_tipo,
            referencia_id=referencia_id,
            registrado_por=request.user,
            observacion=observacion,
        )
        return Response(MovimientoInventarioSerializer(mov).data, status=status.HTTP_200_OK)


class MovimientoInventarioViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MovimientoInventarioSerializer
    permission_classes = [IsAuthenticatedTenant, PuedeGestionarInventario]

    def get_queryset(self):
        return MovimientoInventario.objects.filter(empresa=self.request.tenant).select_related(
            "item_inventario", "registrado_por"
        ).order_by("-created_at")


class SolicitudRepuestoViewSet(viewsets.ModelViewSet):
    serializer_class = SolicitudRepuestoSerializer
    permission_classes = [IsAuthenticatedTenant]

    def get_permissions(self):
        if self.action in ["aprobar"]:
            return [IsAuthenticatedTenant(), PuedeGestionarInventario()]
        if self.action in ["en_proceso_almacen", "marcar_entregada"]:
            return [IsAuthenticatedTenant(), PuedeGestionarInventario()]
        if self.action in ["marcar_recibida_taller"]:
            return [IsAuthenticatedTenant()]
        return [IsAuthenticatedTenant()]

    def get_queryset(self):
        qs = SolicitudRepuesto.objects.filter(empresa=self.request.tenant).prefetch_related("detalles")
        rol = self.request.user.rol.nombre if self.request.user and self.request.user.rol else None
        if rol in ["MECANICO", "MECÁNICO"]:
            qs = qs.filter(
                Q(orden_global__mecanicos_asignados__mecanico=self.request.user)
                | Q(orden_global__detalles__mecanico_asignado=self.request.user)
            ).distinct()
        return qs.order_by("-created_at")

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        if rol not in ["ADMIN", "ASESOR DE SERVICIO"]:
            return Response({"error": "No autorizado para crear solicitudes."}, status=status.HTTP_403_FORBIDDEN)
        cita_id = request.data.get("cita_id")
        orden_id = request.data.get("orden_global_id")
        motivo = request.data.get("motivo", "")
        detalles = request.data.get("detalles", [])
        if not cita_id or not detalles:
            return Response({"error": "cita_id y detalles son requeridos."}, status=status.HTTP_400_BAD_REQUEST)

        solicitud = SolicitudRepuesto.objects.create(
            empresa=request.tenant,
            cita_id=cita_id,
            orden_global_id=orden_id,
            solicitado_por=request.user,
            estado=EstadoSolicitudRepuesto.CREADA,
            motivo=motivo,
        )
        for det in detalles:
            SolicitudRepuestoDetalle.objects.create(
                empresa=request.tenant,
                solicitud=solicitud,
                item_inventario_id=det.get("item_inventario_id"),
                cantidad_solicitada=int(det.get("cantidad_solicitada") or 0),
                cantidad_aprobada=0,
                cantidad_entregada=0,
                estado=EstadoSolicitudRepuestoDetalle.SOLICITADO,
                observacion=det.get("observacion", ""),
            )
        return Response(SolicitudRepuestoSerializer(solicitud).data, status=status.HTTP_201_CREATED)

    def _puede_marcar_recibida_taller(self, request, solicitud):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        if rol in ["ADMIN", "ASESOR DE SERVICIO"]:
            return True
        if rol not in ["MECANICO", "MECÃNICO"]:
            return False
        if not solicitud.orden_global_id:
            return False
        orden = solicitud.orden_global
        if orden.mecanicos_asignados.filter(mecanico=request.user).exists():
            return True
        return orden.detalles.filter(mecanico_asignado=request.user).exists()

    @action(detail=True, methods=["post"], url_path="aprobar")
    @transaction.atomic
    def aprobar(self, request, pk=None, **kwargs):
        solicitud = self.get_object()
        solicitud.estado = EstadoSolicitudRepuesto.APROBADA_POR_ASESOR
        solicitud.aprobado_por_asesor = request.user
        solicitud.observaciones_asesor = request.data.get("observaciones_asesor", "")
        solicitud.save(update_fields=["estado", "aprobado_por_asesor", "observaciones_asesor", "updated_at"])
        return Response(SolicitudRepuestoSerializer(solicitud).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="en-proceso-almacen")
    @transaction.atomic
    def en_proceso_almacen(self, request, pk=None, **kwargs):
        solicitud = self.get_object()
        solicitud.estado = EstadoSolicitudRepuesto.EN_REVISION_ALMACEN
        solicitud.observaciones_almacen = request.data.get("observaciones_almacen", "")
        solicitud.save(update_fields=["estado", "observaciones_almacen", "updated_at"])
        return Response(SolicitudRepuestoSerializer(solicitud).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="marcar-entregada")
    @transaction.atomic
    def marcar_entregada(self, request, pk=None, **kwargs):
        solicitud = self.get_object()
        detalles_payload = request.data.get("detalles", [])
        if not detalles_payload:
            return Response({"error": "Debe enviar detalles de entrega."}, status=status.HTTP_400_BAD_REQUEST)

        for d in detalles_payload:
            det_id = d.get("detalle_id")
            qty = int(d.get("cantidad_entregada") or 0)
            if qty < 0:
                return Response({"error": "Cantidad entregada invalida."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                det = SolicitudRepuestoDetalle.objects.select_related("item_inventario").get(
                    id=det_id, solicitud=solicitud, empresa=request.tenant
                )
            except SolicitudRepuestoDetalle.DoesNotExist:
                continue
            item = det.item_inventario
            if not item:
                continue
            if qty > item.stock_actual:
                return Response({"error": f"Stock insuficiente para item {item.nombre}."}, status=status.HTTP_400_BAD_REQUEST)

            stock_anterior = item.stock_actual
            item.stock_actual = stock_anterior - qty
            item.save(update_fields=["stock_actual", "updated_at"])

            MovimientoInventario.objects.create(
                empresa=request.tenant,
                item_inventario=item,
                tipo_movimiento=TipoMovimientoInventario.SALIDA_TALLER,
                cantidad=-qty,
                stock_anterior=stock_anterior,
                stock_posterior=item.stock_actual,
                referencia_tipo="SolicitudRepuesto",
                referencia_id=solicitud.id,
                registrado_por=request.user,
                observacion=f"Entrega para solicitud {solicitud.id}",
            )

            det.cantidad_aprobada = max(det.cantidad_aprobada, qty)
            det.cantidad_entregada = qty
            det.estado = EstadoSolicitudRepuestoDetalle.ENTREGADO if qty > 0 else det.estado
            det.save(update_fields=["cantidad_aprobada", "cantidad_entregada", "estado", "updated_at"])

        solicitud.estado = EstadoSolicitudRepuesto.ENTREGADA
        solicitud.save(update_fields=["estado", "updated_at"])
        return Response(SolicitudRepuestoSerializer(solicitud).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="marcar-recibida-taller")
    @transaction.atomic
    def marcar_recibida_taller(self, request, pk=None, **kwargs):
        solicitud = self.get_object()
        if not self._puede_marcar_recibida_taller(request, solicitud):
            return Response({"error": "No autorizado para marcar recepcion en taller."}, status=status.HTTP_403_FORBIDDEN)

        detalles_payload = request.data.get("detalles", [])
        if not detalles_payload:
            return Response({"error": "Debe enviar detalles de recepcion."}, status=status.HTTP_400_BAD_REQUEST)

        for d in detalles_payload:
            det_id = d.get("detalle_id")
            qty = int(d.get("cantidad_recibida") or 0)
            if qty < 0:
                return Response({"error": "Cantidad recibida invalida."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                det = SolicitudRepuestoDetalle.objects.get(
                    id=det_id, solicitud=solicitud, empresa=request.tenant
                )
            except SolicitudRepuestoDetalle.DoesNotExist:
                continue

            if qty > det.cantidad_entregada:
                return Response(
                    {"error": f"La cantidad recibida no puede exceder la entregada ({det.cantidad_entregada})."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            det.cantidad_recibida_taller = qty
            if qty > 0:
                det.recibido_taller_at = timezone.now()
                det.recibido_taller_por = request.user
            det.save(
                update_fields=[
                    "cantidad_recibida_taller",
                    "recibido_taller_at",
                    "recibido_taller_por",
                    "updated_at",
                ]
            )

        return Response(SolicitudRepuestoSerializer(solicitud).data, status=status.HTTP_200_OK)



