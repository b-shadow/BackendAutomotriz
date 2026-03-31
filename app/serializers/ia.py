"""Serializers para Inteligencia Artificial."""

from rest_framework import serializers
from app.models import (
    ConversacionIA,
    MensajeIA,
    AccionIA,
)


class ConversacionIASerializer(serializers.ModelSerializer):
    """Serializer base para Conversación IA."""
    usuario_nombres = serializers.CharField(
        source="usuario.nombres",
        read_only=True
    )

    class Meta:
        model = ConversacionIA
        fields = [
            "id",
            "empresa",
            "usuario",
            "usuario_nombres",
            "estado",
            "canal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MensajeIASerializer(serializers.ModelSerializer):
    """Serializer base para Mensaje IA."""

    class Meta:
        model = MensajeIA
        fields = [
            "id",
            "empresa",
            "conversacion",
            "rol_mensaje",
            "contenido",
            "metadata",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class AccionIASerializer(serializers.ModelSerializer):
    """Serializer base para Acción IA."""
    usuario_nombres = serializers.CharField(
        source="usuario.nombres",
        read_only=True
    )

    class Meta:
        model = AccionIA
        fields = [
            "id",
            "empresa",
            "conversacion",
            "usuario",
            "usuario_nombres",
            "accion",
            "parametros",
            "estado",
            "requiere_confirmacion",
            "confirmada_at",
            "ejecutada_at",
            "resultado",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
