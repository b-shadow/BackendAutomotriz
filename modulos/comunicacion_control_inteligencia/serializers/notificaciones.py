"""Serializers para Notificaciones."""

from rest_framework import serializers
from modulos.comunicacion_control_inteligencia.models import (
    NotificacionEntrega,
    Notificacion,
)


class NotificacionEntregaSerializer(serializers.ModelSerializer):
    """Serializer base para Entrega de NotificaciÃ³n."""

    class Meta:
        model = NotificacionEntrega
        fields = [
            "id",
            "empresa",
            "notificacion",
            "canal",
            "estado",
            "destinatario",
            "enviado_at",
            "error_mensaje",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class NotificacionSerializer(serializers.ModelSerializer):
    """Serializer base para NotificaciÃ³n."""
    entregas = NotificacionEntregaSerializer(many=True, read_only=True)

    class Meta:
        model = Notificacion
        fields = [
            "id",
            "empresa",
            "usuario",
            "tipo",
            "titulo",
            "mensaje",
            "entidad_tipo",
            "entidad_id",
            "leida_at",
            "entregas",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

