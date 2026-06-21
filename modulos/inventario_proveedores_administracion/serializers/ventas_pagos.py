"""Serializers para Ventas en Mostrador y Pagos de Taller."""

from django.utils import timezone
from rest_framework import serializers
from modulos.inventario_proveedores_administracion.models import (
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
            "codigo_pago",
            "proveedor",
            "ambiente",
            "tipo_origen",
            "origen_display",
            "tipo_destino",
            "id_destino",
            "cita",
            "venta",
            "estado",
            "monto_total",
            "monto_real",
            "monto_cobrado",
            "monto_pagado",
            "metodo_pago",
            "moneda",
            "referencia",
            "descripcion",
            "qr_payload",
            "qr_imagen_url",
            "qr_imagen_base64",
            "url_pago",
            "referencia_externa",
            "id_pago_proveedor",
            "id_transaccion_proveedor",
            "fecha_expiracion",
            "fecha_pago",
            "metadata",
            "respuesta_proveedor_raw",
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
    pago_estado = serializers.CharField(source="pago_taller.estado", read_only=True)
    pago_metodo = serializers.CharField(source="pago_taller.metodo_pago", read_only=True)
    pago_moneda = serializers.CharField(source="pago_taller.moneda", read_only=True)
    pago_fecha = serializers.DateTimeField(source="pago_taller.fecha_pago", read_only=True)

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
            "html_generado",
            "archivo_pdf_url",
            "pago_estado",
            "pago_metodo",
            "pago_moneda",
            "pago_fecha",
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

