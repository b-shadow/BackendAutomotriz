"""Serializers para gestion de usuarios en el contexto tenant."""
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from modulos.administracion_acceso_configuracion.models import Usuario, Rol
from modulos.administracion_acceso_configuracion.serializers.password_policy import (
    validate_strong_password,
)


class RolSimplesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rol
        fields = ["id", "nombre", "descripcion"]


class UsuarioPropietarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "nombres", "apellidos", "email"]


class UsuarioListadoSerializer(serializers.ModelSerializer):
    rol = RolSimplesSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "nombres",
            "apellidos",
            "email",
            "telefono",
            "rol",
            "is_active",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]


class UsuarioCreadoSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, min_length=8, validators=[validate_strong_password]
    )

    class Meta:
        model = Usuario
        fields = ["id", "nombres", "apellidos", "email", "password", "telefono"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        empresa = self.context.get("empresa")
        if Usuario.objects.filter(empresa=empresa, email=value).exists():
            raise serializers.ValidationError(
                f"Un usuario con email '{value}' ya existe en esta empresa."
            )
        return value

    def create(self, validated_data):
        empresa = self.context.get("empresa")
        rol, _ = Rol.objects.get_or_create(
            empresa=empresa,
            nombre="USUARIO",
            defaults={"descripcion": "Rol de usuario regular", "es_sistema": True},
        )
        validated_data["password"] = make_password(validated_data["password"])
        return Usuario.objects.create(
            empresa=empresa, rol=rol, is_active=True, **validated_data
        )


class UsuarioCambiarRolSerializer(serializers.Serializer):
    rol_id = serializers.UUIDField()

    def validate_rol_id(self, value):
        empresa = self.context.get("empresa")
        usuario = self.context.get("usuario")
        if not Rol.objects.filter(id=value, empresa=empresa).exists():
            raise serializers.ValidationError(
                "El rol especificado no existe en esta empresa."
            )
        usuario_autenticado = self.context.get("usuario_autenticado")
        if usuario_autenticado and usuario.id == usuario_autenticado.id:
            raise serializers.ValidationError("No puedes cambiar tu propio rol.")
        return value

    def update(self, instance, validated_data):
        instance.rol_id = validated_data["rol_id"]
        instance.save()
        return instance


class UsuarioActivarDesactivarSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()

    def update(self, instance, validated_data):
        instance.is_active = validated_data.get("is_active", instance.is_active)
        instance.save()
        return instance


class UsuarioCambiarContrasenaSerializer(serializers.Serializer):
    contrasena_actual = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    contrasena_nueva = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        min_length=8,
        validators=[validate_strong_password],
    )
    contrasena_confirmacion = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def to_internal_value(self, data):
        # Backward compatibility: acepta llaves legacy con caracteres especiales/mojibake.
        mutable = dict(data)
        alias_map = {
            "contrasena_actual": ["contraseña_actual", "contraseÃ±a_actual"],
            "contrasena_nueva": ["contraseña_nueva", "contraseÃ±a_nueva"],
            "contrasena_confirmacion": [
                "contraseña_confirmacion",
                "contraseÃ±a_confirmacion",
            ],
        }
        for canonical, aliases in alias_map.items():
            if canonical not in mutable:
                for alias in aliases:
                    if alias in mutable:
                        mutable[canonical] = mutable[alias]
                        break
        return super().to_internal_value(mutable)

    def validate(self, data):
        if data["contrasena_nueva"] != data["contrasena_confirmacion"]:
            raise serializers.ValidationError(
                {"contrasena_confirmacion": "Las contrasenas no coinciden."}
            )
        return data

    def validate_contrasena_actual(self, value):
        usuario = self.context.get("usuario")
        if not usuario or not usuario.check_password(value):
            raise serializers.ValidationError("La contrasena actual es incorrecta.")
        return value

    def update(self, instance, validated_data):
        instance.set_password(validated_data["contrasena_nueva"])
        instance.save()
        return instance


class UsuarioEditarSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "nombres", "apellidos", "email", "telefono"]
        read_only_fields = ["id"]

    def validate_email(self, value):
        usuario = self.instance
        empresa = usuario.empresa
        if usuario.email == value:
            return value
        if Usuario.objects.filter(empresa=empresa, email=value).exclude(
            id=usuario.id
        ).exists():
            raise serializers.ValidationError(
                f"Un usuario con email '{value}' ya existe en esta empresa."
            )
        return value

    def update(self, instance, validated_data):
        instance.nombres = validated_data.get("nombres", instance.nombres)
        instance.apellidos = validated_data.get("apellidos", instance.apellidos)
        instance.email = validated_data.get("email", instance.email)
        instance.telefono = validated_data.get("telefono", instance.telefono)
        instance.save()
        return instance


class UsuarioDetalleSerializer(serializers.ModelSerializer):
    rol = RolSimplesSerializer(read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id",
            "nombres",
            "apellidos",
            "email",
            "rol",
            "telefono",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class UsuarioPreferenciasNotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["noti_email", "noti_push"]
