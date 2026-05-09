"""Serializers para Presupuestos."""

from decimal import Decimal

from rest_framework import serializers
from modulos.atencion_tecnica_ejecucion.models import (
    PresupuestoCita,
    PresupuestoDetalle,
)
from modulos.inventario_proveedores_administracion.models import PagoTaller, EstadoPagoTaller


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
    pagos_recibidos = serializers.SerializerMethodField()
    saldo_pendiente = serializers.SerializerMethodField()
    porcentaje_pagado = serializers.SerializerMethodField()
    pagos_historial = serializers.SerializerMethodField()

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
            "pagos_recibidos",
            "saldo_pendiente",
            "porcentaje_pagado",
            "pagos_historial",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def _monto_pagado(self, obj):
        total = Decimal("0.00")
        for p in PagoTaller.objects.filter(
            empresa=obj.empresa,
            cita=obj.cita,
        ).exclude(estado=EstadoPagoTaller.ANULADO):
            total += p.monto_total or Decimal("0.00")
        return total

    def get_pagos_recibidos(self, obj):
        return self._monto_pagado(obj)

    def get_saldo_pendiente(self, obj):
        pendiente = (obj.total or Decimal("0.00")) - self._monto_pagado(obj)
        if pendiente < 0:
            pendiente = Decimal("0.00")
        return pendiente

    def get_porcentaje_pagado(self, obj):
        total = obj.total or Decimal("0.00")
        if total <= 0:
            return Decimal("0.00")
        pagado = self._monto_pagado(obj)
        pct = (pagado * Decimal("100.00")) / total
        if pct > Decimal("100.00"):
            pct = Decimal("100.00")
        return pct.quantize(Decimal("0.01"))

    def get_pagos_historial(self, obj):
        pagos = PagoTaller.objects.filter(
            empresa=obj.empresa,
            cita=obj.cita,
        ).exclude(estado=EstadoPagoTaller.ANULADO).order_by("-created_at")
        data = []
        for p in pagos:
            data.append({
                "id": str(p.id),
                "monto": p.monto_total,
                "metodo_pago": p.metodo_pago,
                "estado": p.estado,
                "referencia": p.referencia,
                "registrado_por": (p.registrado_por.nombres if p.registrado_por else None),
                "recibido_at": p.recibido_at,
                "created_at": p.created_at,
            })
        return data
