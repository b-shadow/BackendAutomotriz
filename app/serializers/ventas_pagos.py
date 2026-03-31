"""Serializers para Ventas en Mostrador y Pagos de Taller."""

from django.utils import timezone
from rest_framework import serializers
from app.models import (
    VentaMostradorDetalle,
    VentaMostrador,
    PagoTaller,
    Factura,
    CajaUsuario,
    MovimientoCaja,
)


class VentaMostradorDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para Detalle de Venta en Mostrador."""
    item_nombre = serializers.StringRelatedField(
        source="item_inventario.nombre",
        read_only=True
    )

    class Meta:
        model = VentaMostradorDetalle
        fields = [
            "id",
            "empresa",
            "venta",
            "item_inventario",
            "item_nombre",
            "cantidad",
            "precio_unitario",
            "subtotal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class VentaMostradorSerializer(serializers.ModelSerializer):
    """Serializer base para Venta en Mostrador."""
    detalles = VentaMostradorDetalleSerializer(many=True, read_only=True)
    cliente_nombre = serializers.SerializerMethodField()

    class Meta:
        model = VentaMostrador
        fields = [
            "id",
            "empresa",
            "cliente_usuario",
            "cliente_nombre",
            "cliente_documento",
            "vendido_por",
            "estado",
            "subtotal",
            "total",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_cliente_nombre(self, obj):
        if obj.cliente_usuario:
            return obj.cliente_usuario.nombres
        return obj.cliente_nombre_libre


class PagoTallerSerializer(serializers.ModelSerializer):
    """Serializer base para Pago de Taller."""
    origen_display = serializers.SerializerMethodField()

    class Meta:
        model = PagoTaller
        fields = [
            "id",
            "empresa",
            "tipo_origen",
            "origen_display",
            "cita",
            "venta",
            "estado",
            "monto_total",
            "metodo_pago",
            "moneda",
            "referencia",
            "registrado_por",
            "recibido_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_origen_display(self, obj):
        return obj.get_tipo_origen_display()


class FacturaSerializer(serializers.ModelSerializer):
    """Serializer base para Factura."""

    class Meta:
        model = Factura
        fields = [
            "id",
            "empresa",
            "pago_taller",
            "numero",
            "fecha_emision",
            "nit_razon_social",
            "total",
            "archivo_pdf_url",
            "created_at",
        ]
        read_only_fields = ["id", "fecha_emision", "created_at"]

    def create(self, validated_data):
        """Asignar fecha_emision si no viene en datos."""
        if 'fecha_emision' not in self.initial_data:
            validated_data['fecha_emision'] = timezone.now()
        return super().create(validated_data)


class CajaUsuarioSerializer(serializers.ModelSerializer):
    """Serializer base para Caja de Usuario."""
    administrativo_nombres = serializers.CharField(
        source="administrativo.nombres",
        read_only=True
    )

    class Meta:
        model = CajaUsuario
        fields = [
            "id",
            "empresa",
            "administrativo",
            "administrativo_nombres",
            "nombre",
            "activa",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MovimientoCajaSerializer(serializers.ModelSerializer):
    """Serializer base para Movimiento de Caja."""

    class Meta:
        model = MovimientoCaja
        fields = [
            "id",
            "empresa",
            "caja",
            "tipo",
            "concepto",
            "monto",
            "pago_taller",
            "venta",
            "registrado_por",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
