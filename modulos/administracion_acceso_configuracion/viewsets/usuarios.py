"""ViewSet para gestiÃ³n de usuarios en contexto multi-tenant.
Acciones:
- list: Listar todos los usuarios de la empresa
- create: Crear nuevo usuario (solo ADMIN)
- retrieve: Obtener detalles de un usuario
- update/partial_update: Actualizar usuario (solo ciertos campos)
- cambiar_rol: Cambiar rol de un usuario (solo ADMIN)
- desactivar: Desactivar usuario (solo ADMIN)
- activar: Activar usuario (solo ADMIN)
- obtener_roles: Obtener roles disponibles en la empresa (solo ADMIN)"""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from modulos.administracion_acceso_configuracion.models import Usuario, Rol
from modulos.administracion_acceso_configuracion.serializers.usuarios import (
    UsuarioListadoSerializer,
    UsuarioCreadoSerializer,
    UsuarioCambiarRolSerializer,
    UsuarioActivarDesactivarSerializer,
    UsuarioCambiarContrasenaSerializer,
    UsuarioEditarSerializer,
    UsuarioDetalleSerializer,
    UsuarioPreferenciasNotificacionSerializer,
    RolSimplesSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    registrar_evento_on_commit,
    construir_cambios,
    AccionAuditoria,
)
# PERMISOS PERSONALIZADOS
class IsAdminTenant(permissions.BasePermission):
    """ Permite acceso solo si el usuario es ADMIN de la empresa actual."""
    def has_permission(self, request, view):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False
        # El usuario debe pertenecer al tenant actual
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        # El usuario debe tener rol ADMIN
        if not request.user.rol or request.user.rol.nombre != "ADMIN":
            return False
        return True

class IsAuthenticatedTenant(permissions.BasePermission):
    """ Permite acceso a cualquier usuario autenticado del tenant actual."""
    def has_permission(self, request, view):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False
        
        # El usuario debe pertenecer al tenant actual
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        return True
# VIEWSET DE USUARIOS
class UsuariosViewSet(viewsets.ModelViewSet):
    """ ViewSet para gestiÃ³n de usuarios dentro de una empresa tenant.
    GET /api/{slug}/usuarios/ - Listar usuarios (cualquier autenticado)
    POST /api/{slug}/usuarios/ - Crear usuario (solo ADMIN)
    GET /api/{slug}/usuarios/{id}/ - Detalles usuario
    PATCH /api/{slug}/usuarios/{id}/cambiar-rol/ - Cambiar rol (solo ADMIN)
    PATCH /api/{slug}/usuarios/{id}/desactivar/ - Desactivar (solo ADMIN)
    PATCH /api/{slug}/usuarios/{id}/activar/ - Activar (solo ADMIN)
    GET /api/{slug}/usuarios/obtener-roles/ - Obtener roles (solo ADMIN)
    GET /api/{slug}/usuarios/preferencias-notificacion/ - Obtener preferencias del usuario autenticado
    PATCH /api/{slug}/usuarios/preferencias-notificacion/ - Actualizar preferencias del usuario autenticado"""
    serializer_class = UsuarioDetalleSerializer

    def get_queryset(self):
        """Filtrar usuarios por empresa del tenant."""
        if not hasattr(self.request, "tenant"):
            return Usuario.objects.none()
        return Usuario.objects.filter(empresa=self.request.tenant)

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action == "list" or self.action == "retrieve":
            return UsuarioListadoSerializer
        elif self.action == "create":
            return UsuarioCreadoSerializer
        elif self.action == "cambiar_rol":
            return UsuarioCambiarRolSerializer
        elif self.action in ["desactivar", "activar"]:
            return UsuarioActivarDesactivarSerializer
        elif self.action == "cambiar_contrasena":
            return UsuarioCambiarContrasenaSerializer
        elif self.action == "preferencias_notificacion":
            return UsuarioPreferenciasNotificacionSerializer
        elif self.action in ["update", "partial_update"]:
            return UsuarioEditarSerializer
        return UsuarioDetalleSerializer

    def get_permissions(self):
        """Asignar permisos segÃºn la acciÃ³n.
        - list, retrieve: usuarios autenticados del tenant
        - cambiar_contrasena, partial_update, preferencias_notificacion: usuario autenticado (solo su propio perfil)
        - create, cambiar_rol, desactivar, activar, obtener_roles, update: solo ADMIN"""
        if self.action in ["list", "retrieve", "cambiar_contrasena", "partial_update", "preferencias_notificacion"]:
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["create", "cambiar_rol", "desactivar", "activar", "obtener_roles", "update", "eliminar"]:
            permission_classes = [IsAdminTenant]
        else:
            permission_classes = [IsAuthenticatedTenant]
        return [permission() for permission in permission_classes]

    def get_serializer_context(self):
        """Agregar empresa y usuario autenticado al contexto."""
        context = super().get_serializer_context()
        context["empresa"] = getattr(self.request, "tenant", None)
        context["usuario_autenticado"] = self.request.user
        return context

    def create(self, request, *args, **kwargs):
        """Crear un nuevo usuario en la empresa. POST /api/{slug}/usuarios/
        Body:
        {
            "nombres": "Juan",
            "apellidos": "PÃ©rez",
            "email": "juan@empresa.com",
            "password": "segura123",
            "telefono": "+573001234567" (opcional)
        } """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # AuditorÃ­a: usuario creado
        usuario = serializer.instance
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.USUARIO_CREADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Usuario {usuario.email} creado",
            metadata={
                "email": usuario.email,
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "rol": usuario.rol.nombre if usuario.rol else None,
                "is_active": usuario.is_active,
            }
        )
        # Retornar usuario creado con todos los datos
        response_serializer = UsuarioDetalleSerializer(usuario)
        return Response(
            {
                "mensaje": "Usuario creado exitosamente",
                "usuario": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )
    @action(detail=True, methods=["patch"], url_path="cambiar-rol")
    def cambiar_rol(self, request, pk=None, **kwargs):
        """ Cambiar el rol de un usuario. PATCH /api/{slug}/usuarios/{id}/cambiar-rol/ """
        usuario = self.get_object()
        # Validar que no es el usuario autenticado
        if usuario.id == request.user.id:
            return Response(
                {"error": "No puedes cambiar tu propio rol de usuario."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Guardar rol anterior para auditorÃ­a
        rol_anterior = usuario.rol.nombre if usuario.rol else None
        serializer = self.get_serializer(usuario, data=request.data, partial=True)
        serializer.context["usuario"] = usuario
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # AuditorÃ­a: rol cambiado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.USUARIO_ROL_CAMBIADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Rol de {usuario.email} cambiÃ³ de {rol_anterior} a {usuario.rol.nombre}",
            metadata={
                "usuario_objetivo_id": str(usuario.id),
                "usuario_objetivo_email": usuario.email,
                "rol_anterior": rol_anterior,
                "rol_nuevo": usuario.rol.nombre if usuario.rol else None,
            }
        )
        response_serializer = UsuarioDetalleSerializer(usuario)
        return Response(
            {
                "mensaje": "Rol actualizado exitosamente",
                "usuario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="desactivar")
    def desactivar(self, request, pk=None, **kwargs):
        """ Desactivar un usuario (poner is_active=false). PATCH /api/{slug}/usuarios/{id}/desactivar/"""
        usuario = self.get_object()
        serializer = self.get_serializer(
            usuario,
            data={"is_active": False},
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # AuditorÃ­a: usuario desactivado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.USUARIO_DESACTIVADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Usuario {usuario.email} desactivado",
            metadata={
                "usuario_afectado_id": str(usuario.id),
                "usuario_afectado_email": usuario.email,
                "is_active": usuario.is_active,
            }
        )
        response_serializer = UsuarioDetalleSerializer(usuario)
        return Response(
            {
                "mensaje": "Usuario desactivado exitosamente",
                "usuario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="activar")
    def activar(self, request, pk=None, **kwargs):
        """ Activar un usuario (poner is_active=true).PATCH /api/{slug}/usuarios/{id}/activar/"""
        usuario = self.get_object()
        serializer = self.get_serializer(
            usuario,
            data={"is_active": True},
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # AuditorÃ­a: usuario activado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.USUARIO_ACTIVADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Usuario {usuario.email} activado",
            metadata={
                "usuario_afectado_id": str(usuario.id),
                "usuario_afectado_email": usuario.email,
                "is_active": usuario.is_active,
            }
        )
        response_serializer = UsuarioDetalleSerializer(usuario)
        return Response(
            {
                "mensaje": "Usuario activado exitosamente",
                "usuario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get"], url_path="obtener-roles")
    def obtener_roles(self, request, *args, **kwargs):
        """Obtener lista de roles disponibles en la empresa.
        GET /api/{slug}/usuarios/obtener-roles/"""
        empresa = getattr(request, "tenant", None)
        if not empresa:
            return Response(
                {"error": "Empresa no especificada"},
                status=status.HTTP_400_BAD_REQUEST
            )
        roles = Rol.objects.filter(empresa=empresa)
        serializer = RolSimplesSerializer(roles, many=True)
        return Response({
            "roles": serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["patch"], url_path="cambiar-contrasena")
    def cambiar_contrasena(self, request, *args, **kwargs):
        """ Cambiar contraseÃ±a del usuario autenticado.
        PATCH /api/{slug}/usuarios/cambiar-contrasena/"""
        usuario = request.user
        serializer = self.get_serializer(
            usuario,
            data=request.data,
            context={"usuario": usuario},
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # AuditorÃ­a: contraseÃ±a cambiada (sin exponer secretos)
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.PASSWORD_CAMBIADO,
            usuario=usuario,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"ContraseÃ±a de {usuario.email} fue actualizada",
            metadata={
                "origen": "cambiar_contrasena",
                "usuario_id": str(usuario.id),
                "email": usuario.email,
            }
        )
        return Response(
            {
                "mensaje": "ContraseÃ±a actualizada exitosamente",
                "usuario": UsuarioDetalleSerializer(usuario).data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["get", "patch"], url_path="preferencias-notificacion")
    def preferencias_notificacion(self, request, *args, **kwargs):
        """Obtener o actualizar preferencias de notificaciÃ³n del usuario autenticado.
        GET /api/{slug}/usuarios/preferencias-notificacion/
        PATCH /api/{slug}/usuarios/preferencias-notificacion/"""
        usuario = request.user
        
        if request.method == "GET":
            # Obtener preferencias del usuario autenticado
            serializer = UsuarioPreferenciasNotificacionSerializer(usuario)
            return Response(
                {"preferencias": serializer.data},
                status=status.HTTP_200_OK
            )
        elif request.method == "PATCH":
            # Actualizar preferencias del usuario autenticado
            # Guardar datos anteriores para auditorÃ­a
            datos_anteriores = {
                "noti_email": usuario.noti_email,
                "noti_push": usuario.noti_push,
            }
            serializer = UsuarioPreferenciasNotificacionSerializer(
                usuario,
                data=request.data,
                partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
            # AuditorÃ­a: preferencias de notificaciÃ³n actualizadas
            cambios = construir_cambios(
                datos_anteriores,
                {
                    "noti_email": usuario.noti_email,
                    "noti_push": usuario.noti_push,
                }
            )
            registrar_evento_desde_request(
                request,
                empresa=request.tenant,
                accion=AccionAuditoria.PREFERENCIAS_NOTIFICACION_ACTUALIZADAS,
                usuario=request.user,
                entidad_tipo="Usuario",
                entidad_id=usuario.id,
                descripcion=f"Preferencias de notificaciÃ³n de {usuario.email} fueron actualizadas",
                metadata=cambios
            )
            return Response(
                {
                    "mensaje": "Preferencias de notificaciÃ³n actualizadas exitosamente",
                    "preferencias": UsuarioPreferenciasNotificacionSerializer(usuario).data
                },
                status=status.HTTP_200_OK
            )
    def partial_update(self, request, pk=None, *args, **kwargs):
        """ Editar datos del perfil del usuario (solo si es el usuario autenticado).
        PATCH /api/{slug}/usuarios/{id}/
        
        Campos editables:
        - nombres
        - apellidos
        - email
        - telefono"""
        usuario = self.get_object()
        # Validar que auto-ediciÃ³n o es ADMIN
        is_admin = request.user.rol and request.user.rol.nombre == "ADMIN"
        is_self = usuario.id == request.user.id
        if not is_admin and not is_self:
            return Response(
                {"error": "No autorizado. Solo puedes editar tu propio perfil."},
                status=status.HTTP_403_FORBIDDEN
            )
        # Guardar datos anteriores para auditorÃ­a
        datos_anteriores = {
            "nombres": usuario.nombres,
            "apellidos": usuario.apellidos,
            "email": usuario.email,
            "telefono": usuario.telefono,
        }
        serializer = self.get_serializer(
            usuario,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # AuditorÃ­a: perfil actualizado
        cambios = construir_cambios(
            datos_anteriores,
            {
                "nombres": usuario.nombres,
                "apellidos": usuario.apellidos,
                "email": usuario.email,
                "telefono": usuario.telefono,
            }
        )
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.PERFIL_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario.id,
            descripcion=f"Perfil de {usuario.email} fue actualizado",
            metadata=cambios
        )
        response_serializer = UsuarioDetalleSerializer(usuario)
        return Response(
            {
                "mensaje": "Perfil actualizado exitosamente",
                "usuario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["delete"], url_path="eliminar")
    def eliminar(self, request, pk=None, **kwargs):
        """Eliminar un usuario de la empresa.
        DELETE /api/{slug}/usuarios/{id}/eliminar/"""
        usuario = self.get_object()
        
        # Validar que no sea el usuario autenticado
        if usuario.id == request.user.id:
            return Response(
                {"error": "No puedes eliminarte a ti mismo como usuario."},
                status=status.HTTP_400_BAD_REQUEST
            )
        # Guardar datos antes de eliminar para auditorÃ­a
        usuario_email = usuario.email
        usuario_id = usuario.id
        usuario_rol = usuario.rol.nombre if usuario.rol else None
        # AuditorÃ­a: usuario eliminado (antes de borrar)
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.USUARIO_ELIMINADO,
            usuario=request.user,
            entidad_tipo="Usuario",
            entidad_id=usuario_id,
            descripcion=f"Usuario {usuario_email} fue eliminado",
            metadata={
                "usuario_eliminado_id": str(usuario_id),
                "usuario_eliminado_email": usuario_email,
                "usuario_eliminado_rol": usuario_rol,
            }
        )
        usuario.delete()
        return Response(
            {"mensaje": "Usuario eliminado exitosamente"},
            status=status.HTTP_204_NO_CONTENT
        )

