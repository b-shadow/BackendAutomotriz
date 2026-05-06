from rest_framework.permissions import BasePermission


class IsCompanyAdmin(BasePermission):
    """Permite acceso a usuarios autenticados del tenant con rol ADMIN."""

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        tenant = getattr(request, "tenant", None)
        if tenant is not None and getattr(user, "empresa_id", None) != getattr(tenant, "id", None):
            return False
        rol = getattr(user, "rol", None)
        return bool(rol and getattr(rol, "nombre", "") == "ADMIN")
