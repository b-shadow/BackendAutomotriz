""" ViewSet para gestiÃ³n global de empresas (multi-tenant)."""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

from modulos.administracion_acceso_configuracion.models import Empresa
from modulos.administracion_acceso_configuracion.serializers import EmpresaSerializer
from nucleo.permisos import IsCompanyAdmin


class EmpresaViewSet(viewsets.ModelViewSet):
    """ ViewSet para gestionar empresas a nivel global respetando aislamiento multi-tenant. """
    serializer_class = EmpresaSerializer
    filterset_fields = ['estado', 'slug']

    def get_permissions(self):
        """ Aplica permisos especÃ­ficos segÃºn acciÃ³n y mÃ©todo HTTP. """
        # Acciones pÃºblicas
        if self.action in ['list', 'create']:
            return [permissions.AllowAny()]
        
        # AcciÃ³n retrieve: autenticado para acceder a su empresa
        if self.action == 'retrieve':
            return [permissions.IsAuthenticated()]
        
        # Acciones que modifican: requieren ADMIN
        if self.action in ['update', 'partial_update']:
            return [permissions.IsAuthenticated(), IsCompanyAdmin()]
        
        # Action mi_empresa: diferencia por mÃ©todo HTTP
        if self.action == 'mi_empresa':
            # GET: solo autenticado
            # PATCH: autenticado + ADMIN
            if self.request.method == 'GET':
                return [permissions.IsAuthenticated()]
            else:  # PATCH, PUT, DELETE, etc
                return [permissions.IsAuthenticated(), IsCompanyAdmin()]
        
        # Default para otros actions: autenticado + ADMIN
        return [permissions.IsAuthenticated(), IsCompanyAdmin()]

    def get_object(self):
        """ Segunda capa de seguridad: valida aislamiento multi-tenant en objeto.
        Garantiza que incluso si alguien intenta acceder a /api/empresas/{otro_id}/,
        serÃ¡ explÃ­citamente denegado. Esto previene IDOR (Insecure Direct Object Reference). """
        obj = super().get_object()
        # Validar para acciones que requieren autenticaciÃ³n
        if self.action in ['retrieve', 'update', 'partial_update']:
            if self.request.user.is_authenticated:
                usuario_empresa = getattr(self.request.user, 'empresa', None)
                if usuario_empresa and obj.id != usuario_empresa.id:
                    raise PermissionDenied(
                        "No tiene permiso para acceder a esta empresa. "
                        "Solo puede acceder a su propia empresa."
                    )
        return obj
    def get_queryset(self):
        """ Retorna empresas segÃºn acciÃ³n (aislamiento multi-tenant). """
        # Acciones pÃºblicas: todas las empresas activas
        if self.action in ['list', 'create']:
            return Empresa.objects.filter(estado="ACTIVA")
        
        # Acciones restringidas: solo su empresa
        if self.request.user and self.request.user.is_authenticated:
            if hasattr(self.request.user, 'empresa') and self.request.user.empresa:
                return Empresa.objects.filter(id=self.request.user.empresa.id)
        
        # Sin autenticaciÃ³n: queryset vacÃ­o
        return Empresa.objects.none()

    def destroy(self, request, *args, **kwargs):
        """ Borrado de empresa DESHABILITADO. """
        return Response(
            {"error": "La operaciÃ³n de borrado de empresas no estÃ¡ permitida"},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    @action(detail=False, methods=['get', 'patch'])
    def mi_empresa(self, request):
        """ Obtener o editar datos de la empresa del usuario autenticado. """
        # Los permisos ya validaron autenticaciÃ³n (GET y PATCH)
        # Los permisos tambiÃ©n validaron rol ADMIN para PATCH
        # AquÃ­ solo obtenemos la empresa y procesamos
        
        if not hasattr(request.user, 'empresa') or not request.user.empresa:
            return Response(
                {"error": "Usuario no tiene empresa asociada"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        empresa = request.user.empresa
        
        if request.method == "GET":
            serializer = self.get_serializer(empresa)
            return Response(serializer.data)
        
        if request.method == "PATCH":
            serializer = self.get_serializer(empresa, data=request.data, partial=True)
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


