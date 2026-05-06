"""Serializers para Reportes."""

from rest_framework import serializers
from modulos.comunicacion_control_inteligencia.models import ReporteGenerado


class ReporteGeneradoSerializer(serializers.ModelSerializer):
    """Serializer base para Reporte Generado."""
    generado_por_nombres = serializers.CharField(
        source="generado_por.nombres",
        read_only=True
    )

    class Meta:
        model = ReporteGenerado
        fields = [
            "id",
            "empresa",
            "tipo_reporte",
            "formato",
            "filtros",
            "archivo_url",
            "generado_por",
            "generado_por_nombres",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

