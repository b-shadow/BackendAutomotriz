"""Serializers para autenticación multi-tenant y resolución de tenants.
DISEÑO MULTI-TENANT CORRECTO:
- Cada usuario pertenece a UNA sola empresa (Usuario.empresa = ForeignKey)
- El mismo email puede existir en empresas DISTINTAS como cuentas DIFERENTES
- La contraseña es específica de esa empresa
- NO use Membership para autenticación
- Búsquedas SIEMPRE filtradas por empresa + email """
from rest_framework import serializers
from django.contrib.auth.hashers import make_password, check_password
from app.models import Usuario, Empresa, Rol


class TenantResolveSerializer(serializers.ModelSerializer):
    """Serializer para resolver un tenant por slug."""
    
    class Meta:
        model = Empresa
        fields = ["id", "nombre", "slug", "estado"]


class TenantUserRegisterSerializer(serializers.Serializer):
    """
    Registro de usuario para un tenant específico.
    
    REGLA: Un usuario pertenece a UNA sola empresa.
    - Si juan@gmail.com NO existe en Empresa A => crear Usuario nuevo en Empresa A
    - Si juan@gmail.com YA existe en Empresa A => error (duplicate)
    - Si juan@gmail.com existe en Empresa B => permitir (cuenta diferente en Empresa A)
    
    La búsqueda es SIEMPRE: Usuario.objects.filter(empresa=tenant, email=email)
    """
    email = serializers.EmailField()
    password = serializers.CharField(
        style={"input_type": "password"},
        write_only=True,
        min_length=8
    )
    nombres = serializers.CharField(max_length=255)
    apellidos = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def create(self, validated_data):
        """
        Crea un nuevo Usuario ligado a este tenant.
        
        Validaciones:
        - Obtener empresa desde context (tenant_slug)
        - Buscar Usuario SOLO en esa empresa por email
        - Si existe => error (IntegrityError manejado)
        - Si no existe => crear usuario ligado a empresa
        - Asignar rol USUARIO por defecto
        """
        tenant_slug = self.context.get("tenant_slug")
        
        if not tenant_slug:
            raise serializers.ValidationError("tenant_slug no proporcionado en context")
        
        try:
            tenant = Empresa.objects.get(slug=tenant_slug, estado="ACTIVA")
        except Empresa.DoesNotExist:
            raise serializers.ValidationError("Empresa no encontrada o inactiva")

        email = validated_data["email"]
        password = validated_data["password"]
        nombres = validated_data["nombres"]
        apellidos = validated_data.get("apellidos", "")

        # ===== BÚSQUEDA CORRECTA: FILTRADA POR EMPRESA =====
        # Verificar si ya existe en THIS empresa
        existing_user = Usuario.objects.filter(
            empresa=tenant,
            email=email
        ).first()
        
        if existing_user:
            raise serializers.ValidationError(
                f"El email '{email}' ya está registrado en esta empresa"
            )

        # ===== OBTENER O CREAR ROL USUARIO POR DEFECTO =====
        # Buscar rol USUARIO (creado automáticamente en setup_empresa_nueva)
        # Si no existe (empresa legacy), crearlo automáticamente
        rol_usuario, _ = Rol.objects.get_or_create(
            empresa=tenant,
            nombre="USUARIO",
            defaults={
                "descripcion": "Usuario estándar con acceso a funcionalidades básicas",
                "es_sistema": True,
            }
        )

        # ===== CREAR USUARIO NUEVO CON ROL USUARIO =====
        usuario = Usuario.objects.create(
            empresa=tenant,  # ✅ Ligado a UNA sola empresa
            email=email,
            nombres=nombres,
            apellidos=apellidos,
            rol=rol_usuario,  # ✅ Asignar rol USUARIO por defecto
            is_active=True
        )
        
        # Generar hash de contraseña (AbstractBaseUser lo maneja)
        usuario.set_password(password)
        usuario.save()

        return {
            "usuario": usuario,
            "created": True
        }


class TenantUserLoginSerializer(serializers.Serializer):
    """
    Login de usuario en un tenant específico.
    
    REGLA: Validar SOLO en el contexto de este tenant.
    - Búsqueda: Usuario.objects.filter(empresa=tenant, email=email)
    - Nunca busques globalmente por email
    - Si el usuario no existe EN ESTA EMPRESA => rechazado
    - Aunque exista en otra empresa
    
    Validaciones:
    1. Obtener empresa por slug
    2. Buscar Usuario filtrado por empresa + email
    3. Validar contraseña
    4. Retornar usuario si todo es correcto
    """
    email = serializers.EmailField()
    password = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )

    def validate(self, data):
        """Valida usuario SOLO en el contexto del tenant."""
        email = data.get("email")
        password = data.get("password")
        tenant_slug = self.context.get("tenant_slug")

        if not tenant_slug:
            raise serializers.ValidationError("tenant_slug no proporcionado en context")

        # ===== OBTENER EMPRESA =====
        try:
            tenant = Empresa.objects.get(slug=tenant_slug, estado="ACTIVA")
        except Empresa.DoesNotExist:
            raise serializers.ValidationError("Empresa no encontrada o inactiva")

        # ===== BÚSQUEDA CORRECTA: FILTRADA POR EMPRESA + EMAIL =====
        # NUNCA: Usuario.objects.filter(email=email)  ❌
        # SIEMPRE: Usuario.objects.filter(empresa=tenant, email=email)  ✅
        try:
            usuario = Usuario.objects.get(
                empresa=tenant,
                email=email,
                is_active=True
            )
        except Usuario.DoesNotExist:
            raise serializers.ValidationError(
                "Email o contraseña inválidos"  # No revelar si existe en otra empresa
            )

        # ===== VALIDAR CONTRASEÑA =====
        if not usuario.check_password(password):
            raise serializers.ValidationError("Email o contraseña inválidos")

        # ===== RETORNAR DATOS VALIDADOS =====
        data["usuario"] = usuario
        data["tenant"] = tenant

        return data
