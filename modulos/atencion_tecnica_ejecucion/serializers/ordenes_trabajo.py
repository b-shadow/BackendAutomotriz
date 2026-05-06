"""Serializers para Ã“rdenes de Trabajo."""

from rest_framework import serializers
from django.utils import timezone
from modulos.atencion_tecnica_ejecucion.models import (
    OrdenTrabajoDetalle,
    OrdenTrabajoGlobalMecanico,
    OrdenTrabajoGlobal,
)


class OrdenTrabajoDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para Detalle Orden de Trabajo."""
    servicio_nombre = serializers.StringRelatedField(
        source="servicio_catalogo.nombre",
        read_only=True
    )
    mecanico_nombres = serializers.StringRelatedField(
        source="mecanico_asignado.nombres",
        read_only=True
    )

    class Meta:
        model = OrdenTrabajoDetalle
        fields = [
            "id",
            "empresa",
            "orden_global",
            "servicio_catalogo",
            "servicio_nombre",
            "estado",
            "prioridad",
            "tiempo_estandar_min",
            "tiempo_real_min",
            "mecanico_asignado",
            "mecanico_nombres",
            "visible_cliente",
            "observaciones_asesor",
            "observaciones_mecanico",
            "inicio_real",
            "fin_real",
            "precio_base",
            "orden_visual",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class OrdenTrabajoGlobalMecanicoSerializer(serializers.ModelSerializer):
    """Serializer base para MecÃ¡nico en Orden de Trabajo."""
    mecanico_nombres = serializers.CharField(
        source="mecanico.nombres",
        read_only=True
    )

    class Meta:
        model = OrdenTrabajoGlobalMecanico
        fields = [
            "id",
            "empresa",
            "orden_global",
            "mecanico",
            "mecanico_nombres",
            "es_principal",
            "asignado_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def create(self, validated_data):
        """Asignar tiempo de asignaciÃ³n si no viene en datos."""
        if 'asignado_at' not in self.initial_data:
            validated_data['asignado_at'] = timezone.now()
        return super().create(validated_data)


class OrdenTrabajoGlobalSerializer(serializers.ModelSerializer):
    """Serializer base para Orden de Trabajo Global."""
    detalles = OrdenTrabajoDetalleSerializer(many=True, read_only=True)
    mecanicos_asignados = OrdenTrabajoGlobalMecanicoSerializer(many=True, read_only=True)

    class Meta:
        model = OrdenTrabajoGlobal
        fields = [
            "id",
            "empresa",
            "cita",
            "numero",
            "estado",
            "asesor_responsable",
            "observaciones",
            "fecha_apertura",
            "fecha_cierre",
            "detalles",
            "mecanicos_asignados",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def create(self, validated_data):
        """Asignar fecha_apertura si no viene en datos."""
        if 'fecha_apertura' not in self.initial_data:
            validated_data['fecha_apertura'] = timezone.now()
        return super().create(validated_data)

