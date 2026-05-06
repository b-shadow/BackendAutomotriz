""" Serializers para suscripciones y pagos. """
from rest_framework import serializers
from modulos.administracion_acceso_configuracion.models import Suscripcion, Plan, Pago

class PlanSerializer(serializers.ModelSerializer):
    """Serializer para planes de suscripciÃ³n."""
    precio_formato = serializers.SerializerMethodField()
    class Meta:
        model = Plan
        fields = [
            'id',
            'codigo',
            'nombre',
            'descripcion',
            'duracion_dias',
            'precio_centavos',
            'precio_formato',
            'moneda',
            'activo',
            'created_at',
            'updated_at'
        ]
        read_only_fields = [
            'id',
            'created_at',
            'updated_at'
        ]
    
    def get_precio_formato(self, obj):
        """Retorna el precio formateado."""
        return f"${obj.precio_centavos / 100:.2f}"

class SuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para suscripciones."""
    plan = PlanSerializer(read_only=True)
    plan_nombre = serializers.CharField(source='plan.nombre', read_only=True, allow_null=True)
    plan_precio_centavos = serializers.IntegerField(source='plan.precio_centavos', read_only=True, allow_null=True)
    plan_pendiente = PlanSerializer(read_only=True)
    plan_pendiente_nombre = serializers.CharField(source='plan_pendiente.nombre', read_only=True, allow_null=True)
    plan_pendiente_precio_centavos = serializers.IntegerField(source='plan_pendiente.precio_centavos', read_only=True, allow_null=True)
    tiene_cambio_pendiente = serializers.SerializerMethodField()
    dias_restantes = serializers.SerializerMethodField()
    
    class Meta:
        model = Suscripcion
        fields = [
            'id',
            'empresa_id',
            'plan',
            'plan_nombre',
            'plan_precio_centavos',
            'plan_pendiente',
            'plan_pendiente_nombre',
            'plan_pendiente_precio_centavos',
            'fecha_aplicacion_plan_pendiente',
            'tiene_cambio_pendiente',
            'inicio',
            'fin',
            'estado',
            'dias_restantes',
            'referencia_pago',
            'created_at'
        ]
        read_only_fields = [
            'id',
            'empresa_id',
            'created_at'
        ]
    
    def get_tiene_cambio_pendiente(self, obj):
        """Retorna True si existe un plan pendiente."""
        return obj.plan_pendiente is not None
    
    def get_dias_restantes(self, obj):
        """Calcula los dÃ­as restantes de la suscripciÃ³n."""
        from django.utils import timezone
        if obj.fin:
            delta = obj.fin - timezone.now()
            return max(0, delta.days)
        return -1

class PagoSerializer(serializers.ModelSerializer):
    """Serializer para pagos."""
    plan_nombre = serializers.CharField(source='plan.nombre', read_only=True)
    
    class Meta:
        model = Pago
        fields = [
            'id',
            'empresa_slug',
            'empresa_nombre',
            'usuario_email',
            'usuario_nombres',
            'usuario_apellidos',
            'plan',
            'plan_nombre',
            'amount_centavos',
            'moneda',
            'stripe_payment_intent_id',
            'stripe_session_id',
            'estado',
            'created_at'
        ]
        read_only_fields = [
            'id',
            'created_at',
            'plan_nombre'
        ]


