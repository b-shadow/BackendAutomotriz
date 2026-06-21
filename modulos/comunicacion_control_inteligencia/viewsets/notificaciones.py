from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modulos.comunicacion_control_inteligencia.models import Notificacion
from modulos.comunicacion_control_inteligencia.serializers.notificaciones import (
    NotificacionSerializer,
)


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and hasattr(request, "tenant")
            and request.user.empresa == request.tenant
        )


class NotificacionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificacionSerializer
    permission_classes = [IsAuthenticatedTenant]

    def get_queryset(self):
        queryset = (
            Notificacion.objects.filter(
                empresa=self.request.tenant,
                usuario=self.request.user,
            )
            .prefetch_related("entregas")
            .order_by("-created_at")
        )
        solo_no_leidas = self.request.query_params.get("solo_no_leidas")
        if str(solo_no_leidas).lower() in ["1", "true", "yes"]:
            queryset = queryset.filter(leida_at__isnull=True)
        return queryset

    @action(detail=True, methods=["post"], url_path="marcar-leida")
    def marcar_leida(self, request, pk=None, **kwargs):
        notificacion = self.get_object()
        if not notificacion.leida_at:
            notificacion.leida_at = timezone.now()
            notificacion.save(update_fields=["leida_at"])
        return Response(self.get_serializer(notificacion).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="marcar-todas-leidas")
    def marcar_todas_leidas(self, request, **kwargs):
        updated = self.get_queryset().filter(leida_at__isnull=True).update(leida_at=timezone.now())
        return Response({"updated": updated}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="resumen")
    def resumen(self, request, **kwargs):
        queryset = self.get_queryset()
        return Response(
            {
                "total": queryset.count(),
                "no_leidas": queryset.filter(leida_at__isnull=True).count(),
            },
            status=status.HTTP_200_OK,
        )
