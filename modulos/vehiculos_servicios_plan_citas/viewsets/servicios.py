"""ViewSet para gestiÃ³n de catÃ¡logo de servicios en contexto multi-tenant.
- list: Listar servicios (filtrado segÃºn rol)
- create: Crear nuevo servicio
- retrieve: Obtener detalles de un servicio
- partial_update: Editar servicio (solo asesor/admin)
- estado: Cambiar estado de servicio (activar/inactivar)"""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.db import transaction

from modulos.vehiculos_servicios_plan_citas.models import ServicioCatalogo, Empresa
from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
    ServicioCatalogoListadoSerializer,
    ServicioCatalogoDetalleSerializer,
    ServicioCatalogoCreacionSerializer,
    ServicioCatalogoEdicionSerializer,
    ServicioCatalogoEstadoSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    construir_cambios,
    AccionAuditoria,
)
# PERMISOS PERSONALIZADOS
class IsAuthenticatedTenant(permissions.BasePermission):
    """ Permite acceso a cualquier usuario autenticado del tenant actual. """
    def has_permission(self, request, view):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False
        # El usuario debe pertenecer al tenant actual
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        return True

class PuedeGestionarServicios(permissions.BasePermission):
    """ Permite crear, editar y cambiar estado de servicios solo a ADMIN y ASESOR DE SERVICIO."""
    def has_permission(self, request, view):
        # El usuario debe estar autenticado y en el tenant
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        # El usuario debe tener rol ADMIN o ASESOR DE SERVICIO
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]
# VIEWSET DE SERVICIOS CATÃLOGO
class ServiciosCatalogoViewSet(viewsets.ModelViewSet):
    """ ViewSet para gestiÃ³n del catÃ¡logo de servicios dentro de una empresa tenant.
    GET /api/{slug}/servicios/ - Listar servicios
    POST /api/{slug}/servicios/ - Crear servicio
    GET /api/{slug}/servicios/{id}/ - Detalles servicio
    PATCH /api/{slug}/servicios/{id}/ - Editar servicio (asesor/admin)
    PATCH /api/{slug}/servicios/{id}/estado/ - Cambiar estado (asesor/admin)"""
    serializer_class = ServicioCatalogoDetalleSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["nombre", "codigo", "descripcion"]
    ordering_fields = ["nombre", "codigo", "created_at", "precio_base"]
    ordering = ["nombre"]
    filterset_fields = ["activo"]

    def get_queryset(self):
        """ Filtrar servicios por empresa del tenant.        
        ADMIN y ASESOR DE SERVICIO: ven todos (activos e inactivos)
        USUARIO y MECÃNICO: solo ven activos """
        if not hasattr(self.request, "tenant"):
            return ServicioCatalogo.objects.none()
        queryset = ServicioCatalogo.objects.filter(empresa=self.request.tenant)
        # Filtrado segÃºn rol
        rol_nombre = self.request.user.rol.nombre if self.request.user.rol else None
        # Usuarios y tÃ©cnicos solo ven servicios activos
        if rol_nombre in ["USUARIO", "MECÃNICO"]:
            queryset = queryset.filter(activo=True)
        return queryset.select_related("empresa")

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action == "list":
            return ServicioCatalogoListadoSerializer
        elif self.action == "create":
            return ServicioCatalogoCreacionSerializer
        elif self.action == "estado":
            return ServicioCatalogoEstadoSerializer
        elif self.action in ["update", "partial_update"]:
            return ServicioCatalogoEdicionSerializer
        return ServicioCatalogoDetalleSerializer

    def get_permissions(self):
        """ Asignar permisos segÃºn la acciÃ³n."""
        if self.action in ["list", "retrieve"]:
            # list y retrieve: todos autenticados en tenant
            # el queryset filtra segÃºn rol
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["create", "update", "partial_update", "estado"]:
            # Solo ADMIN y ASESOR DE SERVICIO
            permission_classes = [PuedeGestionarServicios]
        else:
            permission_classes = [IsAuthenticatedTenant]
        return [permission() for permission in permission_classes]

    def get_serializer_context(self):
        """Agregar empresa al contexto."""
        context = super().get_serializer_context()
        context["empresa"] = getattr(self.request, "tenant", None)
        return context

    def check_object_permissions(self, request, obj):
        """ Verificar permisos de objeto. USUARIO y MECÃNICO no pueden ver servicios inactivos."""
        if self.action == "retrieve":
            rol_nombre = request.user.rol.nombre if request.user.rol else None
            # Si es usuario o mecÃ¡nico, solo pueden ver servicios activos
            if rol_nombre in ["USUARIO", "MECÃNICO"] and not obj.activo:
                self.permission_denied(
                    request,
                    message="No tienes permiso para ver este servicio."
                )
        super().check_object_permissions(request, obj)

    def create(self, request, *args, **kwargs):
        """ Crear un nuevo servicio en el catÃ¡logo.
        POST /api/{slug}/servicios/ """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # AuditorÃ­a: servicio creado
        servicio = serializer.instance
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.SERVICIO_CATALOGO_CREADO,
            usuario=request.user,
            entidad_tipo="ServicioCatalogo",
            entidad_id=servicio.id,
            descripcion=f"Servicio '{servicio.nombre}' ({servicio.codigo}) creado",
            metadata={
                "codigo": servicio.codigo,
                "nombre": servicio.nombre,
                "tiempo_estandar_min": servicio.tiempo_estandar_min,
                "precio_base": str(servicio.precio_base),
            }
        )
        # Retornar con serializer de detalle
        response_serializer = ServicioCatalogoDetalleSerializer(
            servicio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": "Servicio creado exitosamente",
                "servicio": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        """ Editar parcialmente un servicio (solo ADMIN y ASESOR DE SERVICIO).
        PATCH /api/{slug}/servicios/{id}/ """
        servicio = self.get_object()
        
        # Guardar estado anterior para auditorÃ­a
        datos_anteriores = {
            "codigo": servicio.codigo,
            "nombre": servicio.nombre,
            "descripcion": servicio.descripcion,
            "tiempo_estandar_min": servicio.tiempo_estandar_min,
            "precio_base": str(servicio.precio_base),
        }
        serializer = self.get_serializer(servicio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Construir cambios para auditorÃ­a
        datos_nuevos = {
            "codigo": servicio.codigo,
            "nombre": servicio.nombre,
            "descripcion": servicio.descripcion,
            "tiempo_estandar_min": servicio.tiempo_estandar_min,
            "precio_base": str(servicio.precio_base),
        }
        cambios = construir_cambios(datos_anteriores, datos_nuevos)
        # AuditorÃ­a: servicio actualizado
        if cambios["campos_modificados"]:  # Solo registrar si hay cambios
            registrar_evento_desde_request(
                request,
                empresa=request.tenant,
                accion=AccionAuditoria.SERVICIO_CATALOGO_ACTUALIZADO,
                usuario=request.user,
                entidad_tipo="ServicioCatalogo",
                entidad_id=servicio.id,
                descripcion=f"Servicio '{servicio.nombre}' ({servicio.codigo}) actualizado",
                metadata=cambios
            )
        response_serializer = ServicioCatalogoDetalleSerializer(
            servicio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": "Servicio actualizado exitosamente",
                "servicio": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="estado")
    def estado(self, request, pk=None, **kwargs):
        """ Cambiar el estado (activo/inactivo) de un servicio.
        PATCH /api/{slug}/servicios/{id}/estado/"""
        servicio = self.get_object()
        serializer = self.get_serializer(servicio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        # Guardar estado actual para auditorÃ­a
        estado_anterior = servicio.activo
        nuevo_estado = serializer.validated_data.get("activo")
        motivo = serializer.validated_data.get("motivo", "")
        # Actualizar el servicio
        servicio.activo = nuevo_estado
        servicio.save()
        # AuditorÃ­a: cambio de estado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.SERVICIO_CATALOGO_ESTADO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="ServicioCatalogo",
            entidad_id=servicio.id,
            descripcion=f"Servicio '{servicio.nombre}' ({servicio.codigo}) {'activado' if nuevo_estado else 'inactivado'}",
            metadata={
                "estado_anterior": estado_anterior,
                "estado_nuevo": nuevo_estado,
                "motivo": motivo,
            }
        )
        response_serializer = ServicioCatalogoDetalleSerializer(
            servicio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": f"Servicio {'activado' if nuevo_estado else 'inactivado'} exitosamente",
                "servicio": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

