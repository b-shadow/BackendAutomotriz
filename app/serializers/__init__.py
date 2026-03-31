"""
Serializers para la API SaaS multi-tenant.
Incluye serializers para autenticación, usuarios, empresas, planes, suscripciones y auditoría.
"""
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from app.models import Usuario, Empresa, Plan, Rol, Suscripcion, Auditoria

# Importar serializers específicos de usuarios
from app.serializers.usuarios import (
    UsuarioListadoSerializer,
    UsuarioCreadoSerializer,
    UsuarioCambiarRolSerializer,
    UsuarioActivarDesactivarSerializer,
    UsuarioDetalleSerializer,
    RolSimplesSerializer,
)

# Importar serializers del taller
from app.serializers.taller import (
    # Vehículos y planes
    VehiculoSerializer,
    PlanServicioVehiculoSerializer,
    PlanServicioDetalleSerializer,
    ServicioCatalogoSerializer,
    # Espacios
    EspacioTrabajoSerializer,
    HorarioEspacioTrabajoSerializer,
    # Citas
    CitaSerializer,
    CitaEspacioSegmentoSerializer,
    AvanceVehiculoSerializer,
    # Presupuestos
    PresupuestoCitaSerializer,
    PresupuestoDetalleSerializer,
    # Órdenes de trabajo
    OrdenTrabajoGlobalSerializer,
    OrdenTrabajoDetalleSerializer,
    OrdenTrabajoGlobalMecanicoSerializer,
    # Inventario
    CategoriaInventarioSerializer,
    ItemInventarioSerializer,
    ProveedorSerializer,
    CompraSerializer,
    CompraDetalleSerializer,
    MovimientoInventarioSerializer,
    # Solicitudes
    SolicitudRepuestoSerializer,
    SolicitudRepuestoDetalleSerializer,
    # Ventas y pagos
    VentaMostradorSerializer,
    VentaMostradorDetalleSerializer,
    PagoTallerSerializer,
    FacturaSerializer,
    CajaUsuarioSerializer,
    MovimientoCajaSerializer,
    # Notificaciones
    NotificacionSerializer,
    NotificacionEntregaSerializer,
    # IA
    ConversacionIASerializer,
    MensajeIASerializer,
    AccionIASerializer,
    # Reportes
    ReporteGeneradoSerializer,
)


# ============================================================================
# SERIALIZERS DE AUTENTICACIÓN
# ============================================================================

class LoginSerializer(serializers.Serializer):
    """
    Serializer para login en el contexto de una empresa.
    El usuario proporciona email y password, nosotros buscamos en la empresa del contexto.
    """
    email = serializers.EmailField()
    password = serializers.CharField(style={"input_type": "password"}, write_only=True)

    def validate(self, data):
        """Valida las credenciales contra la empresa del contexto."""
        email = data.get("email")
        password = data.get("password")
        request = self.context.get("request")
        empresa = request.tenant if request else None

        if not empresa:
            raise serializers.ValidationError("No se especificó empresa en la URL")

        # Buscar usuario en esta empresa específicamente
        try:
            usuario = Usuario.objects.get(
                empresa=empresa,
                email=email,
                is_active=True
            )
        except Usuario.DoesNotExist:
            raise serializers.ValidationError("Email o contraseña inválidos")

        # Verificar password
        if not usuario.check_password(password):
            raise serializers.ValidationError("Email o contraseña inválidos")

        data["usuario"] = usuario
        return data


class CambiarContraseñaSerializer(serializers.Serializer):
    """Serializer para cambiar contraseña."""
    password_actual = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )
    password_nueva = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )
    password_confirmacion = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )

    def validate(self, data):
        """Valida que la contraseña nueva coincida con la confirmación."""
        if data["password_nueva"] != data["password_confirmacion"]:
            raise serializers.ValidationError(
                {"password_confirmacion": "Las contraseñas no coinciden"}
            )
        
        if len(data["password_nueva"]) < 6:
            raise serializers.ValidationError(
                {"password_nueva": "La contraseña debe tener al menos 6 caracteres"}
            )
        
        return data


class RecuperarContraseñaSerializer(serializers.Serializer):
    """Serializer para solicitar recuperación de contraseña."""
    email = serializers.EmailField()


class ResetearContraseñaSerializer(serializers.Serializer):
    """Serializer para resetear contraseña con token."""
    token = serializers.CharField()
    password_nueva = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )
    password_confirmacion = serializers.CharField(
        style={"input_type": "password"},
        write_only=True
    )

    def validate(self, data):
        """Valida que las contraseñas coincidan."""
        if data["password_nueva"] != data["password_confirmacion"]:
            raise serializers.ValidationError(
                {"password_confirmacion": "Las contraseñas no coinciden"}
            )
        return data


# ============================================================================
# SERIALIZERS DE USUARIO
# ============================================================================

class UsuarioSerializer(serializers.ModelSerializer):
    """Serializer completo para datos de Usuario."""
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        style={"input_type": "password"}
    )
    rol_nombre = serializers.CharField(source="rol.nombre", read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id", "email", "nombres", "apellidos", "telefono",
            "rol", "rol_nombre", "is_active", "last_login", "created_at",
            "updated_at", "password"
        ]
        read_only_fields = ["id", "created_at", "last_login", "updated_at"]

    def create(self, validated_data):
        """Crea usuario con password hasheado."""
        password = validated_data.pop("password", None)
        usuario = Usuario.objects.create(**validated_data)
        if password:
            usuario.set_password(password)
            usuario.save()
        return usuario

    def update(self, instance, validated_data):
        """Actualiza usuario."""
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class UsuarioListaSerializer(serializers.ModelSerializer):
    """Serializer simplificado para listar usuarios."""
    rol_nombre = serializers.CharField(source="rol.nombre", read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id", "email", "nombres", "apellidos", "rol", "rol_nombre",
            "is_active", "last_login", "created_at"
        ]
        read_only_fields = ["id", "created_at", "last_login"]


class UsuarioPerfilSerializer(serializers.ModelSerializer):
    """Serializer para ver y editar perfil de usuario."""
    rol_nombre = serializers.CharField(source="rol.nombre", read_only=True)

    class Meta:
        model = Usuario
        fields = [
            "id", "email", "nombres", "apellidos", "telefono",
            "rol", "rol_nombre", "is_active", "last_login", "created_at"
        ]
        read_only_fields = ["id", "email", "is_active", "last_login", "created_at"]


# ============================================================================
# SERIALIZERS DE EMPRESA
# ============================================================================

class EmpresaListaSerializer(serializers.ModelSerializer):
    """Serializer simplificado para listar empresas."""

    class Meta:
        model = Empresa
        fields = [
            "id", "nombre", "slug", "estado", "suscripcion_hasta", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


class EmpresaSerializer(serializers.ModelSerializer):
    """Serializer completo para Empresa."""
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = Empresa
        fields = [
            "id", "nombre", "slug", "estado", "estado_display",
            "suscripcion_hasta", "created_at", "updated_at"
        ]
        read_only_fields = ["id", "created_at", "updated_at", "estado_display"]

    def validate_slug(self, value):
        """Valida que el slug sea único."""
        if Empresa.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug ya está en uso")
        return value


class EmpresaRegistroSerializer(serializers.ModelSerializer):
    """Serializer para registrar nuevas empresas."""
    admin_email = serializers.EmailField(write_only=True)
    admin_nombres = serializers.CharField(write_only=True)
    admin_apellidos = serializers.CharField(write_only=True)
    admin_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"}
    )

    class Meta:
        model = Empresa
        fields = [
            "nombre", "slug", "admin_email", "admin_nombres",
            "admin_apellidos", "admin_password"
        ]

    def validate_slug(self, value):
        """Valida slug único."""
        if Empresa.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug ya está en uso")
        return value

    def create(self, validated_data):
        """
        Crea empresa, usuario admin y suscripción inicial.
        
        La suscripción se crea automáticamente con el plan básico.
        """
        from app.services.empresa_setup import setup_empresa_nueva
        
        admin_email = validated_data.pop("admin_email")
        admin_nombres = validated_data.pop("admin_nombres")
        admin_apellidos = validated_data.pop("admin_apellidos")
        admin_password = validated_data.pop("admin_password")

        with transaction.atomic():
            # 1. Crear empresa
            empresa = Empresa.objects.create(**validated_data)
            
            # 2. Crear usuario admin para la empresa
            usuario_admin = Usuario.objects.create(
                empresa=empresa,
                email=admin_email,
                nombres=admin_nombres,
                apellidos=admin_apellidos,
                is_active=True
            )
            usuario_admin.set_password(admin_password)
            usuario_admin.save()
            
            # 3. Setup automático: crear roles base y asignar ADMIN
            setup_empresa_nueva(empresa, usuario_admin)
            
            # 4. Crear suscripción inicial con plan básico
            try:
                plan_basico = Plan.objects.get(codigo="BASICO", activo=True)
            except Plan.DoesNotExist:
                # Si no existe el plan BASICO, crear uno por defecto
                plan_basico = Plan.objects.create(
                    codigo="BASICO",
                    nombre="Plan Básico",
                    descripcion="Plan básico con funcionalidades esenciales",
                    duracion_dias=30,
                    precio_centavos=2999,
                    moneda="USD",
                    activo=True
                )
            
            # Crear suscripción para la empresa
            Suscripcion.objects.create(
                empresa=empresa,
                plan=plan_basico,
                inicio=timezone.now(),
                fin=timezone.now() + timedelta(days=30),
                estado="ACTIVA"
            )

        return empresa


# ============================================================================
# SERIALIZERS DE PLANES
# ============================================================================

class PlanSerializer(serializers.ModelSerializer):
    """Serializer para Planes."""
    moneda_display = serializers.CharField(source="get_moneda_display", read_only=True)
    precio_usd = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = [
            "id", "codigo", "nombre", "descripcion", "duracion_dias",
            "precio_centavos", "moneda", "moneda_display", "precio_usd", "activo", "created_at"
        ]
        read_only_fields = ["id", "created_at"]

    def get_precio_usd(self, obj):
        """Retorna el precio en USD (centavos / 100)."""
        return obj.precio_centavos / 100


# ============================================================================
# SERIALIZERS DE ROLES
# ============================================================================

class RolSerializer(serializers.ModelSerializer):
    """Serializer para Roles."""

    class Meta:
        model = Rol
        fields = [
            "id", "nombre", "descripcion", "es_sistema", "created_at"
        ]
        read_only_fields = ["id", "created_at"]


# ============================================================================
# SERIALIZERS DE SUSCRIPCIONES
# ============================================================================

class SuscripcionSerializer(serializers.ModelSerializer):
    """Serializer para Suscripciones."""
    plan_nombre = serializers.CharField(source="plan.nombre", read_only=True)
    plan_codigo = serializers.CharField(source="plan.codigo", read_only=True)
    plan_precio_centavos = serializers.IntegerField(source="plan.precio_centavos", read_only=True)
    plan_duracion_dias = serializers.IntegerField(source="plan.duracion_dias", read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    dias_restantes = serializers.SerializerMethodField()

    class Meta:
        model = Suscripcion
        fields = [
            "id", "empresa", "plan", "plan_nombre", "plan_codigo", "plan_precio_centavos",
            "plan_duracion_dias", "inicio", "fin", "estado", "estado_display", "dias_restantes",
            "renovacion_de", "referencia_pago", "notas", "created_at"
        ]
        read_only_fields = [
            "id", "empresa", "created_at", "dias_restantes", "estado"
        ]

    def get_dias_restantes(self, obj):
        """Calcula los días restantes hasta el fin de la suscripción."""
        from django.utils import timezone
        if obj.fin:
            delta = obj.fin - timezone.now()
            return max(0, delta.days)
        return None


class SuscripcionCambioSerializer(serializers.Serializer):
    """Serializer para cambiar de plan de suscripción."""
    plan_id = serializers.IntegerField()
    fecha_inicio = serializers.DateField(required=False)

    def validate_plan_id(self, value):
        """Valida que el plan exista y esté activo."""
        try:
            plan = Plan.objects.get(id=value, activo=True)
        except Plan.DoesNotExist:
            raise serializers.ValidationError("Plan no encontrado o inactivo")
        return value

# ============================================================================
# SERIALIZERS DE PAGOS (STRIPE)
# ============================================================================

class PagoSerializer(serializers.Serializer):
    """Serializer base para pagos (lectura)."""
    id = serializers.UUIDField(read_only=True)
    empresa_slug = serializers.CharField(read_only=True)
    empresa_nombre = serializers.CharField(read_only=True)
    usuario_email = serializers.CharField(read_only=True)
    usuario_nombres = serializers.CharField(read_only=True)
    plan = serializers.PrimaryKeyRelatedField(read_only=True)
    amount_centavos = serializers.IntegerField(read_only=True)
    moneda = serializers.CharField(read_only=True)
    estado = serializers.CharField(read_only=True)
    stripe_payment_intent_id = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class RegistroEmpresaConPagoSerializer(serializers.Serializer):
    """
    Serializer para registrar una nueva empresa con pago.
    Paso 1: Usuario proporciona datos y se crea Payment Intent en Stripe.
    """
    # Datos de la empresa
    empresa_nombre = serializers.CharField(max_length=255)
    empresa_slug = serializers.CharField(max_length=255)
    
    # Datos del usuario admin
    usuario_nombres = serializers.CharField(max_length=255)
    usuario_apellidos = serializers.CharField(max_length=255, required=False, allow_blank=True)
    usuario_email = serializers.EmailField()
    usuario_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        min_length=6
    )
    
    # Plan seleccionado
    plan_id = serializers.UUIDField()
    
    # Información del cliente para Stripe
    customer_email = serializers.EmailField(required=False)  # Si es diferente de usuario_email
    customer_name = serializers.CharField(max_length=255, required=False)
    
    def validate_empresa_slug(self, value):
        """Valida que el slug no exista."""
        if Empresa.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Este slug ya está en uso")
        return value
    
    def validate_plan_id(self, value):
        """Valida que el plan exista y esté activo."""
        try:
            Plan.objects.get(id=value, activo=True)
        except Plan.DoesNotExist:
            raise serializers.ValidationError("Plan no encontrado o inactivo")
        return value
    
    def validate(self, data):
        """Validaciones adicionales."""
        # Email del usuario debe ser único globalmente (para el pago)
        if Usuario.objects.filter(email=data['usuario_email']).exists():
            raise serializers.ValidationError({
                'usuario_email': 'Este email ya está registrado'
            })
        
        return data


class ConfirmarPagoSerializer(serializers.Serializer):
    """
    Serializer para confirmar un pago completado en Stripe.
    Paso 2: Stripe notifica que el pago fue exitoso, creamos empresa y usuario.
    """
    payment_intent_id = serializers.CharField(max_length=255)
    
    def validate_payment_intent_id(self, value):
        """Valida que el payment intent exista y esté pendiente."""
        from app.models import Pago
        try:
            pago = Pago.objects.get(
                stripe_payment_intent_id=value,
                estado="PENDIENTE"
            )
        except Pago.DoesNotExist:
            raise serializers.ValidationError("Pago no encontrado o ya procesado")
        return value


class PaymentIntentResponseSerializer(serializers.Serializer):
    """
    Serializer para retornar los datos del Payment Intent.
    Se devuelve al cliente para que complete el pago.
    """
    pago_id = serializers.UUIDField()
    payment_intent_id = serializers.CharField()
    client_secret = serializers.CharField()  # Para Stripe.js
    amount_centavos = serializers.IntegerField()
    moneda = serializers.CharField()
    empresa_nombre = serializers.CharField()
    usuario_email = serializers.CharField()


# ============================================================================
# SERIALIZERS DE AUDITORÍA
# ============================================================================

class AuditoriaSerializer(serializers.ModelSerializer):
    """Serializer para eventos de auditoría."""
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
            "created_at"
        ]
        read_only_fields = [
            "id",
            "empresa",
            "empresa_nombre",
            "empresa_slug",
            "usuario",
            "usuario_id",
            "usuario_nombres",
            "usuario_apellidos",
            "usuario_email",
            "created_at"
        ]