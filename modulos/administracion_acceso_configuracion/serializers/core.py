"""Serializers base del modulo de administracion/acceso/configuracion."""

from rest_framework import serializers
from modulos.administracion_acceso_configuracion.serializers.password_policy import (
    validate_strong_password,
)

from modulos.administracion_acceso_configuracion.models import (
    Auditoria,
    Empresa,
    Pago,
    Plan,
)


class EmpresaSerializer(serializers.ModelSerializer):
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = Empresa
        fields = [
            "id",
            "nombre",
            "slug",
            "estado",
            "estado_display",
            "suscripcion_hasta",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "estado_display"]

    def validate_slug(self, value):
        if Empresa.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug ya está en uso")
        return value


class PlanSerializer(serializers.ModelSerializer):
    precio_formato = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "duracion_dias",
            "precio_centavos",
            "precio_formato",
            "moneda",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_precio_formato(self, obj):
        return f"${obj.precio_centavos / 100:.2f}"


class RegistroEmpresaConPagoSerializer(serializers.Serializer):
    empresa_nombre = serializers.CharField(max_length=255)
    empresa_slug = serializers.CharField(max_length=255)
    usuario_nombres = serializers.CharField(max_length=255)
    usuario_apellidos = serializers.CharField(max_length=255, required=False, allow_blank=True)
    usuario_email = serializers.EmailField()
    usuario_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        min_length=8,
        validators=[validate_strong_password],
    )
    plan_id = serializers.UUIDField()
    customer_email = serializers.EmailField(required=False)
    customer_name = serializers.CharField(max_length=255, required=False)

    def validate_empresa_slug(self, value):
        if Empresa.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug ya está en uso")
        return value

    def validate_plan_id(self, value):
        try:
            Plan.objects.get(id=value, activo=True)
        except Plan.DoesNotExist:
            raise serializers.ValidationError("Plan no encontrado o inactivo")
        return value

    def validate(self, data):
        from modulos.administracion_acceso_configuracion.models import Usuario

        if Usuario.objects.filter(email=data["usuario_email"]).exists():
            raise serializers.ValidationError({"usuario_email": "Este email ya está registrado"})
        return data


class ConfirmarPagoSerializer(serializers.Serializer):
    payment_intent_id = serializers.CharField(max_length=255)

    def validate_payment_intent_id(self, value):
        try:
            Pago.objects.get(stripe_payment_intent_id=value, estado="PENDIENTE")
        except Pago.DoesNotExist:
            raise serializers.ValidationError("Pago no encontrado o ya procesado")
        return value


class PaymentIntentResponseSerializer(serializers.Serializer):
    pago_id = serializers.UUIDField()
    payment_intent_id = serializers.CharField()
    client_secret = serializers.CharField()
    amount_centavos = serializers.IntegerField()
    moneda = serializers.CharField()
    empresa_nombre = serializers.CharField()
    usuario_email = serializers.CharField()


class AuditoriaSerializer(serializers.ModelSerializer):
    usuario_nombres = serializers.CharField(source="usuario.nombres", read_only=True, allow_null=True)
    usuario_apellidos = serializers.CharField(source="usuario.apellidos", read_only=True, allow_null=True)
    usuario_email = serializers.CharField(source="usuario.email", read_only=True, allow_null=True)
    usuario_id = serializers.CharField(source="usuario.id", read_only=True, allow_null=True)
    empresa_nombre = serializers.CharField(source="empresa.nombre", read_only=True)
    empresa_slug = serializers.CharField(source="empresa.slug", read_only=True)

    class Meta:
        model = Auditoria
        fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "empresa_slug",
            "usuario",
            "usuario_id",
            "usuario_nombres",
            "usuario_apellidos",
            "usuario_email",
            "accion",
            "entidad_tipo",
            "entidad_id",
            "descripcion",
            "metadata",
            "ip",
            "user_agent",
            "created_at",
        ]
        read_only_fields = fields
