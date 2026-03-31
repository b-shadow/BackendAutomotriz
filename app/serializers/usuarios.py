""" Serializers para gestión de usuarios en el contexto tenant. """
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from app.models import Usuario, Rol

class RolSimplesSerializer(serializers.ModelSerializer):
    """Serializer simple para mostrar un rol."""
    class Meta:
        model = Rol
        fields = ["id", "nombre", "descripcion"]

class UsuarioPropietarioSerializer(serializers.ModelSerializer):
    """ Serializer simple para mostrar propietario en listas de vehículos. """
    class Meta:
        model = Usuario
        fields = ["id", "nombres", "apellidos", "email"]

class UsuarioListadoSerializer(serializers.ModelSerializer):
    """ Serializer para listar usuarios de una empresa. """
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
    """ Serializer para crear un nuevo usuario en la empresa. El rol se asigna "USUARIO" """
    password = serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model = Usuario
        fields = [
            "id",
            "nombres",
            "apellidos",
            "email",
            "password",
            "telefono",
        ]
        read_only_fields = ["id"]
    def validate_email(self, value):
        """Validar que email sea único dentro de la empresa."""
        empresa = self.context.get("empresa")
        if Usuario.objects.filter(empresa=empresa, email=value).exists():
            raise serializers.ValidationError(
                f"Un usuario con email '{value}' ya existe en esta empresa."
            )
        return value

    def create(self, validated_data):
        """ Crear usuario con rol USUARIO por defecto. """
        empresa = self.context.get("empresa")
        # Obtener o crear rol USUARIO
        rol, _ = Rol.objects.get_or_create(
            empresa=empresa,
            nombre="USUARIO",
            defaults={
                "descripcion": "Rol de usuario regular",
                "es_sistema": True,
            }
        )
        # Hashear password
        validated_data["password"] = make_password(validated_data["password"])  
        # Crear usuario
        usuario = Usuario.objects.create(
            empresa=empresa,
            rol=rol,
            is_active=True,
            **validated_data
        )
        return usuario

class UsuarioCambiarRolSerializer(serializers.Serializer):
    """ Serializer para cambiar el rol de un usuario. """
    rol_id = serializers.UUIDField()
    def validate_rol_id(self, value):
        """Validar que el rol existe en la empresa actual."""
        empresa = self.context.get("empresa")
        usuario = self.context.get("usuario")

        # Validar que el rol existe y pertenece a la empresa
        if not Rol.objects.filter(id=value, empresa=empresa).exists():
            raise serializers.ValidationError(
                "El rol especificado no existe en esta empresa."
            )
        # NO permitir cambiar el rol del usuario autenticado
        usuario_autenticado = self.context.get("usuario_autenticado")
        if usuario_autenticado and usuario.id == usuario_autenticado.id:
            raise serializers.ValidationError(
                "No puedes cambiar tu propio rol de usuario."
            )
        return value

    def update(self, instance, validated_data):
        """Actualizar el rol del usuario."""
        instance.rol_id = validated_data["rol_id"]
        instance.save()
        return instance

class UsuarioActivarDesactivarSerializer(serializers.Serializer):
    """ Serializer para activar/desactivar un usuario. """
    is_active = serializers.BooleanField()
    def update(self, instance, validated_data):
        """Actualizar estado del usuario."""
        instance.is_active = validated_data.get("is_active", instance.is_active)
        instance.save()
        return instance

class UsuarioCambiarContrasenaSerializer(serializers.Serializer):
    """ Serializer para que un usuario cambie su propia contraseña. """
    contraseña_actual = serializers.CharField(
        write_only=True,
        style={"input_type": "password"}
    )
    contraseña_nueva = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        min_length=8
    )
    contraseña_confirmacion = serializers.CharField(
        write_only=True,
        style={"input_type": "password"}
    )
    def validate(self, data):
        """Validar que las contraseñas sean válidas."""
        if data["contraseña_nueva"] != data["contraseña_confirmacion"]:
            raise serializers.ValidationError({
                "contraseña_confirmacion": "Las contraseñas no coinciden."
            })
        if len(data["contraseña_nueva"]) < 8:
            raise serializers.ValidationError({
                "contraseña_nueva": "La contraseña debe tener al menos 8 caracteres."
            })
        return data

    def validate_contraseña_actual(self, value):
        """Validar que la contraseña actual sea correcta."""
        usuario = self.context.get("usuario")
        if not usuario or not usuario.check_password(value):
            raise serializers.ValidationError(
                "La contraseña actual es incorrecta."
            )
        return value

    def update(self, instance, validated_data):
        """Actualizar la contraseña del usuario."""
        instance.set_password(validated_data["contraseña_nueva"])
        instance.save()
        return instance

class UsuarioEditarSerializer(serializers.ModelSerializer):
    """ Serializer para editar perfil básico de un usuario (nombres, apellidos, teléfono). """
    class Meta:
        model = Usuario
        fields = [
            "id",
            "nombres",
            "apellidos",
            "email",
            "telefono",
        ]
        read_only_fields = ["id"]

    def validate_email(self, value):
        """ Validar que el email no esté siendo usado por otro usuario en la misma empresa. """
        usuario = self.instance
        empresa = usuario.empresa
        # Si el email no cambió, está ok
        if usuario.email == value:
            return value
        # Si el email cambió, validar que no exista otro usuario con ese email en la empresa
        if Usuario.objects.filter(empresa=empresa, email=value).exclude(id=usuario.id).exists():
            raise serializers.ValidationError(
                f"Un usuario con email '{value}' ya existe en esta empresa."
            )
        return value

    def update(self, instance, validated_data):
        """Actualizar los datos del usuario."""
        instance.nombres = validated_data.get("nombres", instance.nombres)
        instance.apellidos = validated_data.get("apellidos", instance.apellidos)
        instance.email = validated_data.get("email", instance.email)
        instance.telefono = validated_data.get("telefono", instance.telefono)
        instance.save()
        return instance

class UsuarioDetalleSerializer(serializers.ModelSerializer):
    """ Serializer detallado para mostrar un usuario después de cambios. """
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
    """ Serializer para obtener y actualizar preferencias de notificación de un usuario. """
    class Meta:
        model = Usuario
        fields = [
            "noti_email",
            "noti_push",
        ]
