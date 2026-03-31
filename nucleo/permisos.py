"""
Permisos personalizados para DRF.
Define permisos por rol y nivel de acceso.
"""
from rest_framework import permissions


class IsAuthenticated(permissions.IsAuthenticated):
    """
    Solo usuarios autenticados.
    """

    pass


class IsCompanyAdmin(permissions.BasePermission):
    """
    Solo permite acceso si el usuario es ADMIN de su empresa (tenant).
    
    Valida el rol exacto "ADMIN" (no acepta aliases como 'ADMINISTRADOR', 'admin_empresa', etc).
    """

    def has_permission(self, request, view):
        """Verifica si el usuario es admin de su empresa."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request.user, 'rol') or not request.user.rol:
            return False
        
        # El usuario debe tener exactamente el rol "ADMIN"
        rol_name = request.user.rol.nombre if hasattr(request.user.rol, 'nombre') else str(request.user.rol)
        return rol_name == "ADMIN"


class IsOwnerOrganization(permissions.BasePermission):
    """
    Solo permite acceso si el usuario es OWNER de la organización.
    """

    def has_object_permission(self, request, view, obj):
        # obj es una Organización o un objeto relacionado
        if hasattr(obj, "miembros"):
            # Es una Organización
            try:
                from apps.empresas.models import Membresia

                membresia = obj.miembros.get(usuario=request.user)
                return membresia.rol == Membresia.OWNER
            except:
                return False
        return False


class IsAdminOrganization(permissions.BasePermission):
    """
    Solo permite acceso si el usuario es ADMIN o OWNER de la organización.
    """

    def has_object_permission(self, request, view, obj):
        try:
            from apps.empresas.models import Membresia

            if hasattr(obj, "miembros"):
                membresia = obj.miembros.get(usuario=request.user)
                return membresia.rol in [Membresia.OWNER, Membresia.ADMIN]
            elif hasattr(obj, "empresa"):
                membresia = obj.empresa.miembros.get(usuario=request.user)
                return membresia.rol in [Membresia.OWNER, Membresia.ADMIN]
        except:
            return False
        return False


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Permite acceso de lectura a todos, pero solo el dueño puede editar.
    """

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True

        return obj.usuario == request.user


class ReadOnly(permissions.BasePermission):
    """
    Solo lectura (GET, HEAD, OPTIONS).
    """

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS
