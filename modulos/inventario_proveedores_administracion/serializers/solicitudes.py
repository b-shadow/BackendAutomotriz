"""Serializers para Solicitudes de Repuestos."""

from rest_framework import serializers
from modulos.inventario_proveedores_administracion.models import (
    SolicitudRepuestoDetalle,
    SolicitudRepuesto,
)


class SolicitudRepuestoDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para Detalle de Solicitud de Repuesto."""
    item_nombre = serializers.CharField(
        source="item_inventario.nombre",
        read_only=True
    )

    class Meta:
        model = SolicitudRepuestoDetalle
        fields = [
            "id",
            "empresa",
            "solicitud",
            "item_inventario",
            "item_nombre",
            "cantidad_solicitada",
            "cantidad_aprobada",
            "cantidad_entregada",
            "estado",
            "observacion",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class SolicitudRepuestoSerializer(serializers.ModelSerializer):
    """Serializer base para Solicitud de Repuesto."""
    detalles = SolicitudRepuestoDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = SolicitudRepuesto
        fields = [
            "id",
            "empresa",
            "cita",
            "orden_global",
            "solicitado_por",
            "aprobado_por_asesor",
            "estado",
            "motivo",
            "observaciones_asesor",
            "observaciones_almacen",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

