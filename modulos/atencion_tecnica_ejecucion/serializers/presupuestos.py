"""Serializers para Presupuestos."""

from rest_framework import serializers
from modulos.atencion_tecnica_ejecucion.models import (
    PresupuestoCita,
    PresupuestoDetalle,
)


class PresupuestoDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para Detalle de Presupuesto."""
    servicio_nombre = serializers.CharField(
        source="servicio_catalogo.nombre",
        read_only=True
    )

    class Meta:
        model = PresupuestoDetalle
        fields = [
            "id",
            "empresa",
            "presupuesto",
            "servicio_catalogo",
            "servicio_nombre",
            "descripcion",
            "cantidad",
            "tiempo_estandar_min",
            "precio_unitario",
            "subtotal",
            "estado",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PresupuestoCitaSerializer(serializers.ModelSerializer):
    """Serializer base para Presupuesto Cita."""
    detalles = PresupuestoDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = PresupuestoCita
        fields = [
            "id",
            "empresa",
            "cita",
            "estado",
            "subtotal",
            "descuento",
            "total",
            "comunicado_por",
            "comunicado_at",
            "observaciones",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

