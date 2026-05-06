"""ViewSets para autenticaciÃ³n multi-tenant y resoluciÃ³n de tenants."""
from rest_framework import status, permissions
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.administracion_acceso_configuracion.serializers.tenant_auth import (
    TenantResolveSerializer,
    TenantUserRegisterSerializer,
    TenantUserLoginSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    AccionAuditoria,
)
# ENDPOINT: Resolver tenant por slug
@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def resolve_tenant(request):
    """GET /api/tenants/resolve/slug=:slug
    Resuelve un tenant por slug. Retorna datos bÃ¡sicos si existe. """
    slug = request.query_params.get("slug")
    if not slug:
        return Response(
            {"error": "El parÃ¡metro 'slug' es requerido"},
            status=status.HTTP_400_BAD_REQUEST
        )
    try:
        empresa = Empresa.objects.get(slug=slug, estado="ACTIVA")
        serializer = TenantResolveSerializer(empresa)
        return Response(serializer.data, status=status.HTTP_200_OK)
    except Empresa.DoesNotExist:
        return Response(
            {"error": "Empresa no encontrada o no activa"},
            status=status.HTTP_404_NOT_FOUND
        )
# ENDPOINT: Registro de usuario en tenant
@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def tenant_register(request, tenant_slug):
    """ POST /api/tenants/<slug>/auth/register/
    Registro de usuario INDEPENDIENTE en un tenant. """
    serializer = TenantUserRegisterSerializer(
        data=request.data,
        context={"tenant_slug": tenant_slug}
    )
    if serializer.is_valid():
        result = serializer.save()
        usuario = result["usuario"]
        # AuditorÃ­a: usuario registrado en tenant
        registrar_evento_desde_request(
            request,
            empresa=usuario.empresa,
            accion=AccionAuditoria.USUARIO_REGISTRADO_TENANT,
            usuario=usuario,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Usuario {usuario.email} registrado en el tenant",
            metadata={
                "email": usuario.email,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "rol": usuario.rol.nombre if usuario.rol else None,
                "origen": "tenant_register",
                "is_active": usuario.is_active,
            }
        )
        # Generar JWT correcto con RefreshToken.for_user()
        refresh = RefreshToken.for_user(usuario)
        return Response({
            "usuario": {
                "id": str(usuario.id),
                "email": usuario.email,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "empresa_id": str(usuario.empresa_id),
                "rol": usuario.rol.nombre if usuario.rol else None,
                "rol_id": str(usuario.rol_id) if usuario.rol_id else None,
            },
            "tenant": {
                "id": str(usuario.empresa.id),
                "slug": usuario.empresa.slug,
                "nombre": usuario.empresa.nombre,
            },
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
# ENDPOINT: Login de usuario en tenant
@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def tenant_login(request, tenant_slug):
    """ POST /api/tenants/<slug>/auth/login/
    Login de usuario en un tenant especÃ­fico.
    Body:
    {
        "email": "juan@empresa.com",
        "password": "segura123456"
    }
    Respuesta exitosa (200):
    {
        "usuario": {
            "id": "uuid",
            "email": "juan@empresa.com",
            "nombres": "Juan",
            "empresa_id": "uuid"
        },
        "tenant": {
            "id": "uuid",
            "slug": "empresa-demo",
            "nombre": "Empresa Demo"
        },
        "tokens": {
            "access": "eyJ0...",
            "refresh": "eyJ0..."
        }
    }
    REGLA IMPORTANTE:
    - Si juan@gmail.com existe SOLO en Empresa A:
      - Login en Empresa A con contraseÃ±a correcta => âœ… Permitido
    - Si juan@gmail.com existe en Empresa B (diferente):
      - Login en Empresa A => âŒ Rechazado (no existe en A)
    - Si juan@gmail.com existe en Empresa A con contraseÃ±a abc123:
      - Login con contraseÃ±a xyz789 => âŒ Rechazado
    Errores:
    - 400: Email o contraseÃ±a invÃ¡lidos (genÃ©rico)
    - 400: Datos invÃ¡lidos
    """
    serializer = TenantUserLoginSerializer(
        data=request.data,
        context={"tenant_slug": tenant_slug}
    )
    
    if serializer.is_valid():
        usuario = serializer.validated_data["usuario"]
        tenant = serializer.validated_data["tenant"]
        
        # AuditorÃ­a: login exitoso en tenant
        registrar_evento_desde_request(
            request,
            empresa=tenant,
            accion=AccionAuditoria.USUARIO_LOGIN_TENANT,
            usuario=usuario,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Usuario {usuario.email} iniciÃ³ sesiÃ³n en el tenant",
            metadata={
                "email": usuario.email,
                "rol": usuario.rol.nombre if usuario.rol else None,
                "origen": "tenant_login",
            }
        )
        
        # Generar JWT correcto con RefreshToken.for_user()
        refresh = RefreshToken.for_user(usuario)
        
        return Response({
            "usuario": {
                "id": str(usuario.id),
                "email": usuario.email,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "empresa_id": str(usuario.empresa_id),
                "rol": usuario.rol.nombre if usuario.rol else None,
                "rol_id": str(usuario.rol_id) if usuario.rol_id else None,
            },
            "tenant": {
                "id": str(tenant.id),
                "slug": tenant.slug,
                "nombre": tenant.nombre,
            },
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            }
        }, status=status.HTTP_200_OK)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
# ENDPOINT: Logout de usuario en tenant
@api_view(["POST"])
def tenant_logout(request, tenant_slug):
    """POST /api/tenants/<slug>/auth/logout/
    Cierra la sesiÃ³n del usuario actual revocando su sesiÃ³n.
    Requiere autenticaciÃ³n (JWT token vÃ¡lido). """
    # Validar que la empresa existe
    try:
        empresa = Empresa.objects.get(slug=tenant_slug, estado="ACTIVA")
    except Empresa.DoesNotExist:
        return Response(
            {"error": "Empresa no encontrada o no activa"},
            status=status.HTTP_404_NOT_FOUND
        )
    # Obtener usuario del request (debe estar autenticado)
    usuario = request.user
    if not usuario or usuario.is_anonymous:
        return Response(
            {"error": "No autenticado"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    # Validar que pertenece a la empresa
    if usuario.empresa_id != empresa.id:
        return Response(
            {"error": "Usuario no pertenece a esta empresa"},
            status=status.HTTP_403_FORBIDDEN
        )
    # Revocar sesiÃ³n: actualizar session_revoked_at
    usuario.session_revoked_at = timezone.now()
    usuario.save(update_fields=['session_revoked_at'])
    # Registrar auditorÃ­a
    registrar_evento_desde_request(
        request,
        empresa=empresa,
        accion=AccionAuditoria.USUARIO_LOGOUT_TENANT,
        usuario=usuario,
        entidad_tipo="Usuario",
        entidad_id=usuario.id,
        descripcion=f"Usuario {usuario.email} cerrÃ³ sesiÃ³n",
        metadata={
            "email": usuario.email,
            "nombres": usuario.nombres,
            "rol": usuario.rol.nombre if usuario.rol else None,
            "origen": "tenant_logout",
        }
    )
    return Response({
        "success": True,
        "message": "SesiÃ³n cerrada correctamente"
    }, status=status.HTTP_200_OK)

