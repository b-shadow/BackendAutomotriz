"""Middleware para detectar la empresa desde la URL.
Extrae el slug de empresa del path y lo inyecta en el request.
Ejemplos de URLs:
- /api/empresa-demo/usuarios/login/
- /api/globex/usuarios/
- /api/acme/dashboard/"""
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
from modulos.administracion_acceso_configuracion.models import Empresa
from modulos.comunicacion_control_inteligencia.services.backups import BackupService


class TenantMiddleware(MiddlewareMixin):
    """Middleware que detecta la empresa desde la URL.
    Inyecta `request.tenant` con la instancia de Empresa."""

    def process_request(self, request):
        """ Extrae el slug de empresa de la URL y busca la empresa.
        URL pattern: /api/{empresa_slug}/..."""
        # Rutas que no requieren empresa (rutas globales)
        excluded_paths = [
            "/admin/", 
            "/api/docs/", 
            "/api/schema/",
            "/api/redoc/",
            "/api/auth/",       
            "/api/tenants/",    # AutenticaciÃ³n por tenant (global)
            "/api/pagos/",      # Pagos (global)
            "/api/planes/",     # Planes (global)
            "/api/empresas/",   # Empresas (global)
        ]
        if any(request.path.startswith(path) for path in excluded_paths):
            request.tenant = None
            return None
        # Extraer slug de la URL
        # Path: /api/empresa-demo/login/
        path_parts = request.path.strip("/").split("/")
        # Esperamos: api / empresa_slug / ...
        if len(path_parts) < 2 or path_parts[0] != "api":
            request.tenant = None
            return None
        empresa_slug = path_parts[1]
        # BÃšSQUEDA DE EMPRESA
        try:
            empresa = Empresa.objects.select_related().get(
                slug=empresa_slug,
                estado="ACTIVA"
            )
            request.tenant = empresa
            request.tenant_id = str(empresa.id)
            try:
                # Ejecuta backups automáticos pendientes (incluye compensación por caída)
                BackupService.run_due_backups_for_empresa(empresa)
            except Exception:
                # No bloquear request operativo por fallas de backup
                pass
            
        except Empresa.DoesNotExist:
            # Empresa no existe o estÃ¡ inactiva
            return JsonResponse(
                {
                    "detail": f"Empresa '{empresa_slug}' no encontrada o estÃ¡ inactiva",
                    "code": "tenant_not_found"
                },
                status=404
            )
        except Exception as e:
            return JsonResponse(
                {
                    "detail": "Error al procesar la empresa",
                    "error": str(e)
                },
                status=500
            )
        return None

