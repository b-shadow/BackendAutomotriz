from rest_framework import permissions, status, viewsets
from rest_framework.response import Response

from modulos.atencion_tecnica_ejecucion.models import AvanceVehiculo


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.user.empresa == request.tenant
        )


class AvanceVehiculoViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticatedTenant]

    def get_queryset(self):
        qs = AvanceVehiculo.objects.filter(empresa=self.request.tenant).select_related("cita", "orden_detalle", "registrado_por")
        rol = self.request.user.rol.nombre if self.request.user and self.request.user.rol else None
        if rol == "USUARIO":
            qs = qs.filter(cita__cliente=self.request.user, visible_cliente=True)
        return qs.order_by("-created_at")

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            rol = self.request.user.rol.nombre if self.request.user and self.request.user.rol else None
            if rol not in ["ADMIN", "ASESOR DE SERVICIO", "MECANICO", "MECÁNICO"]:
                return [permissions.IsAdminUser()]
        return super().get_permissions()

    def list(self, request, *args, **kwargs):
        data = []
        for a in self.get_queryset():
            data.append(
                {
                    "id": str(a.id),
                    "cita": str(a.cita_id),
                    "orden_detalle": str(a.orden_detalle_id) if a.orden_detalle_id else None,
                    "tipo": a.tipo,
                    "estado_nuevo": a.estado_nuevo,
                    "mensaje": a.mensaje if (a.visible_cliente or (request.user.rol and request.user.rol.nombre != "USUARIO")) else "",
                    "porcentaje_avance": a.porcentaje_avance,
                    "visible_cliente": a.visible_cliente,
                    "registrado_por": a.registrado_por.nombres if a.registrado_por else None,
                    "created_at": a.created_at,
                }
            )
        return Response(data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        porcentaje = request.data.get("porcentaje_avance")
        if porcentaje is not None:
            try:
                porcentaje = int(porcentaje)
            except Exception:
                return Response({"error": "Porcentaje invalido."}, status=status.HTTP_400_BAD_REQUEST)
            if porcentaje < 0 or porcentaje > 100:
                return Response({"error": "El porcentaje debe estar entre 0 y 100."}, status=status.HTTP_400_BAD_REQUEST)

        avance = AvanceVehiculo.objects.create(
            empresa=request.tenant,
            cita_id=request.data.get("cita"),
            orden_detalle_id=request.data.get("orden_detalle"),
            registrado_por=request.user,
            tipo=request.data.get("tipo", "GENERAL"),
            estado_nuevo=request.data.get("estado_nuevo", ""),
            mensaje=request.data.get("mensaje", ""),
            porcentaje_avance=porcentaje,
            visible_cliente=bool(request.data.get("visible_cliente", True)),
        )
        return Response({"id": str(avance.id)}, status=status.HTTP_201_CREATED)
