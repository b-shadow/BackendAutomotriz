"""Serializers para Inventario."""

from rest_framework import serializers
from app.models import (
    CategoriaInventario,
    ItemInventario,
    Proveedor,
    CompraDetalle,
    Compra,
    MovimientoInventario,
)


class CategoriaInventarioSerializer(serializers.ModelSerializer):
    """Serializer base para Categoría de Inventario."""

    class Meta:
        model = CategoriaInventario
        fields = [
            "id",
            "empresa",
            "nombre",
            "descripcion",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ItemInventarioSerializer(serializers.ModelSerializer):
    """Serializer base para Item de Inventario."""
    categoria_nombre = serializers.CharField(
        source="categoria.nombre",
        read_only=True
    )

    class Meta:
        model = ItemInventario
        fields = [
            "id",
            "empresa",
            "categoria",
            "categoria_nombre",
            "codigo",
            "nombre",
            "descripcion",
            "tipo_item",
            "unidad_medida",
            "stock_actual",
            "stock_minimo",
            "costo_promedio",
            "precio_venta",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ProveedorSerializer(serializers.ModelSerializer):
    """Serializer base para Proveedor."""

    class Meta:
        model = Proveedor
        fields = [
            "id",
            "empresa",
            "nombre",
            "telefono",
            "email",
            "direccion",
            "contacto",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CompraDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para Detalle de Compra."""
    item_nombre = serializers.CharField(
        source="item_inventario.nombre",
        read_only=True
    )

    class Meta:
        model = CompraDetalle
        fields = [
            "id",
            "empresa",
            "compra",
            "item_inventario",
            "item_nombre",
            "cantidad",
            "costo_unitario",
            "subtotal",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CompraSerializer(serializers.ModelSerializer):
    """Serializer base para Compra."""
    detalles = CompraDetalleSerializer(many=True, read_only=True)
    proveedor_nombre = serializers.CharField(
        source="proveedor.nombre",
        read_only=True
    )

    class Meta:
        model = Compra
        fields = [
            "id",
            "empresa",
            "proveedor",
            "proveedor_nombre",
            "numero_documento",
            "estado",
            "fecha_compra",
            "subtotal",
            "total",
            "registrado_por",
            "observaciones",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class MovimientoInventarioSerializer(serializers.ModelSerializer):
    """Serializer base para Movimiento de Inventario."""
    item_nombre = serializers.CharField(
        source="item_inventario.nombre",
        read_only=True
    )

    class Meta:
        model = MovimientoInventario
        fields = [
            "id",
            "empresa",
            "item_inventario",
            "item_nombre",
            "tipo_movimiento",
            "cantidad",
            "stock_anterior",
            "stock_posterior",
            "referencia_tipo",
            "referencia_id",
            "registrado_por",
            "observacion",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
