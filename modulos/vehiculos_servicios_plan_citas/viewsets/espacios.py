"""
ViewSet para gestiÃ³n de espacios de trabajo y horarios en contexto multi-tenant.

Acciones de Espacios:
- list: Listar espacios (filtrado segÃºn rol)
- create: Crear nuevo espacio
- retrieve: Obtener detalles de un espacio
- partial_update: Editar espacio (solo asesor/admin)
- estado: Cambiar estado de espacio (asesor/admin)
- activo: Activar/inactivar espacio (asesor/admin)

Acciones de Horarios:
- list_horarios: Listar horarios de un espacio
- create_horario: Crear horario para espacio
- partial_update_horario: Editar horario
- activo_horario: Cambiar estado activo/inactivo

REGLAS DE NEGOCIO:
1. ADMIN/ASESOR DE SERVICIO: 
   - Acceso completo a espacios y horarios
   
2. USUARIO/MECÃNICO/ADMINISTRATIVO/ALMACENERO: 
   - Solo pueden listar/consultar espacios (read-only)
   
3. CÃ³digo Ãºnico por empresa (espacios)
4. AuditorÃ­a en creaciÃ³n, ediciÃ³n, cambio de estado y cambio de activo
5. ValidaciÃ³n de horarios: hora_inicio < hora_fin
"""
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import transaction

from modulos.vehiculos_servicios_plan_citas.models import EspacioTrabajo, HorarioEspacioTrabajo, Empresa
from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
    EspacioTrabajoListadoSerializer,
    EspacioTrabajoDetalleSerializer,
    EspacioTrabajoCreacionSerializer,
    EspacioTrabajoEdicionSerializer,
    EspacioTrabajoEstadoSerializer,
    EspacioTrabajoActivoSerializer,
    HorarioEspacioTrabajoListadoSerializer,
    HorarioEspacioTrabajoCreacionSerializer,
    HorarioEspacioTrabajoEdicionSerializer,
    HorarioEspacioTrabajoActivoSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    construir_cambios,
    AccionAuditoria,
)


# ============================================================================
# PERMISOS PERSONALIZADOS
# ============================================================================

class IsAuthenticatedTenant(permissions.BasePermission):
    """
    Permite acceso a cualquier usuario autenticado del tenant actual.
    """
    def has_permission(self, request, view):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False
        
        # El usuario debe pertenecer al tenant actual
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        return True


class PuedeGestionarEspacios(permissions.BasePermission):
    """
    Permite crear, editar, cambiar estado y gestionar horarios de espacios
    solo a ADMIN y ASESOR DE SERVICIO.
    """
    def has_permission(self, request, view):
        # El usuario debe estar autenticado y en el tenant
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        # El usuario debe tener rol ADMIN o ASESOR DE SERVICIO
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]


# ============================================================================
# VIEWSET DE ESPACIOS DE TRABAJO
# ============================================================================

class EspaciosTrabajoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestiÃ³n de espacios de trabajo dentro de una empresa tenant.
    
    Endpoints:
    - GET /api/{slug}/espacios/ - Listar espacios
    - POST /api/{slug}/espacios/ - Crear espacio
    - GET /api/{slug}/espacios/{id}/ - Detalles espacio
    - PATCH /api/{slug}/espacios/{id}/ - Editar espacio (asesor/admin)
    - PATCH /api/{slug}/espacios/{id}/estado/ - Cambiar estado (asesor/admin)
    - PATCH /api/{slug}/espacios/{id}/activo/ - Activar/inactivar (asesor/admin)
    - GET /api/{slug}/espacios/{id}/horarios/ - Listar horarios
    - POST /api/{slug}/espacios/{id}/horarios/ - Crear horario
    - PATCH /api/{slug}/espacios/horarios/{horario_id}/ - Editar horario
    - PATCH /api/{slug}/espacios/horarios/{horario_id}/activo/ - Cambiar activo
    - DELETE /api/{slug}/espacios/{id}/eliminar_horario/ - Eliminar horario
    """
    serializer_class = EspacioTrabajoDetalleSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["nombre", "codigo"]
    ordering_fields = ["nombre", "codigo", "tipo", "estado", "created_at"]
    ordering = ["nombre"]
    filterset_fields = ["tipo", "estado", "activo"]

    def get_queryset(self):
        """
        Filtrar espacios por empresa del tenant.
        
        ADMIN y ASESOR DE SERVICIO: ven todos
        Otros roles: tambiÃ©n ven todos (pero con permisos de escritura restringidos)
        """
        if not hasattr(self.request, "tenant"):
            return EspacioTrabajo.objects.none()
        
        queryset = EspacioTrabajo.objects.filter(empresa=self.request.tenant)
        
        return queryset.select_related("empresa").prefetch_related("horarios")

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action == "list":
            return EspacioTrabajoListadoSerializer
        elif self.action == "create":
            return EspacioTrabajoCreacionSerializer
        elif self.action == "estado":
            return EspacioTrabajoEstadoSerializer
        elif self.action == "activo":
            return EspacioTrabajoActivoSerializer
        elif self.action in ["update", "partial_update"]:
            return EspacioTrabajoEdicionSerializer
        elif self.action in ["horarios", "list_horarios"]:
            return HorarioEspacioTrabajoListadoSerializer
        elif self.action == "crear_horario":
            return HorarioEspacioTrabajoCreacionSerializer
        elif self.action == "editar_horario":
            return HorarioEspacioTrabajoEdicionSerializer
        elif self.action == "activo_horario":
            return HorarioEspacioTrabajoActivoSerializer
        return EspacioTrabajoDetalleSerializer

    def get_permissions(self):
        """
        Asignar permisos segÃºn la acciÃ³n.
        """
        if self.action in ["list", "retrieve", "horarios", "list_horarios"]:
            # list, retrieve y horarios: todos autenticados en tenant
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["create", "update", "partial_update", "estado", "activo", 
                            "crear_horario", "editar_horario", "activo_horario", "eliminar_horario"]:
            # Solo ADMIN y ASESOR DE SERVICIO
            permission_classes = [PuedeGestionarEspacios]
        else:
            permission_classes = [IsAuthenticatedTenant]
        
        return [permission() for permission in permission_classes]

    def get_serializer_context(self):
        """Agregar empresa al contexto."""
        context = super().get_serializer_context()
        context["empresa"] = getattr(self.request, "tenant", None)
        return context

    def create(self, request, *args, **kwargs):
        """
        Crear un nuevo espacio de trabajo.
        POST /api/{slug}/espacios/
        
        Body:
        {
            "codigo": "TALLER_1",
            "nombre": "Taller Principal",
            "tipo": "TALLER",
            "observaciones": "Espacio principal de taller"
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        
        # AuditorÃ­a: espacio creado
        espacio = serializer.instance
        
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.ESPACIO_TRABAJO_CREADO,
            usuario=request.user,
            entidad_tipo="EspacioTrabajo",
            entidad_id=espacio.id,
            descripcion=f"Espacio '{espacio.nombre}' ({espacio.codigo}) creado",
            metadata={
                "codigo": espacio.codigo,
                "nombre": espacio.nombre,
                "tipo": espacio.tipo,
                "activo": espacio.activo,
            }
        )
        
        # Retornar con serializer de detalle
        response_serializer = EspacioTrabajoDetalleSerializer(
            espacio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": "Espacio creado exitosamente",
                "espacio": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        """
        Editar parcialmente un espacio (solo ADMIN y ASESOR DE SERVICIO).
        PATCH /api/{slug}/espacios/{id}/
        
        Body:
        {
            "nombre": "Taller Principal Renovado",
            "observaciones": "...",
        }
        """
        espacio = self.get_object()
        
        # Guardar estado anterior para auditorÃ­a
        datos_anteriores = {
            "codigo": espacio.codigo,
            "nombre": espacio.nombre,
            "tipo": espacio.tipo,
            "observaciones": espacio.observaciones,
            "activo": espacio.activo,
        }
        
        serializer = self.get_serializer(espacio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        
        # Construir cambios para auditorÃ­a
        datos_nuevos = {
            "codigo": espacio.codigo,
            "nombre": espacio.nombre,
            "tipo": espacio.tipo,
            "observaciones": espacio.observaciones,
            "activo": espacio.activo,
        }
        cambios = construir_cambios(datos_anteriores, datos_nuevos)
        
        # AuditorÃ­a: espacio actualizado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.ESPACIO_TRABAJO_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="EspacioTrabajo",
            entidad_id=espacio.id,
            descripcion=f"Espacio '{espacio.nombre}' actualizado",
            metadata=cambios
        )
        
        response_serializer = EspacioTrabajoDetalleSerializer(
            espacio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": "Espacio actualizado exitosamente",
                "espacio": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="estado")
    def estado(self, request, pk=None, **kwargs):
        """
        Cambiar estado de un espacio de trabajo.
        PATCH /api/{slug}/espacios/{id}/estado/
        
        Body:
        {
            "estado": "MANTENIMIENTO",
            "motivo": "Mantenimiento preventivo"
        }
        """
        espacio = self.get_object()
        
        serializer = self.get_serializer(espacio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        estado_anterior = espacio.estado
        serializer.save()
        
        # AuditorÃ­a: estado cambiado
        motivo = request.data.get("motivo", "")
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.ESPACIO_TRABAJO_ESTADO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="EspacioTrabajo",
            entidad_id=espacio.id,
            descripcion=f"Estado de espacio '{espacio.nombre}' cambiÃ³ de {estado_anterior} a {espacio.estado}",
            metadata={
                "estado_anterior": estado_anterior,
                "estado_nuevo": espacio.estado,
                "motivo": motivo,
            }
        )
        
        response_serializer = EspacioTrabajoDetalleSerializer(
            espacio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": "Estado del espacio actualizado exitosamente",
                "espacio": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="activo")
    def activo(self, request, pk=None, **kwargs):
        """
        Activar o inactivar un espacio de trabajo.
        PATCH /api/{slug}/espacios/{id}/activo/
        
        Body:
        {
            "activo": false,
            "motivo": "Espacio descontinuado"
        }
        """
        espacio = self.get_object()
        
        serializer = self.get_serializer(espacio, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        activo_anterior = espacio.activo
        serializer.save()
        
        # AuditorÃ­a: cambio de activo
        motivo = request.data.get("motivo", "")
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.ESPACIO_TRABAJO_ACTIVO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="EspacioTrabajo",
            entidad_id=espacio.id,
            descripcion=f"Espacio '{espacio.nombre}' cambiÃ³ de {'activo' if activo_anterior else 'inactivo'} a {'activo' if espacio.activo else 'inactivo'}",
            metadata={
                "activo_anterior": activo_anterior,
                "activo_nuevo": espacio.activo,
                "motivo": motivo,
            }
        )
        
        response_serializer = EspacioTrabajoDetalleSerializer(
            espacio, 
            context=self.get_serializer_context()
        )
        return Response(
            {
                "mensaje": f"Espacio {'activado' if espacio.activo else 'inactivado'} exitosamente",
                "espacio": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["get", "post"], url_path="horarios")
    def horarios(self, request, pk=None, **kwargs):
        """
        Listar o crear horarios de un espacio de trabajo.
        
        GET /api/{slug}/espacios/{id}/horarios/
        - Lista todos los horarios del espacio
        
        POST /api/{slug}/espacios/{id}/horarios/
        - Crea un nuevo horario para el espacio
        
        Body (POST):
        {
            "dia_semana": 0,  // 0=Lunes, 6=Domingo
            "hora_inicio": "08:00:00",
            "hora_fin": "17:00:00"
        }
        """
        espacio = self.get_object()
        
        if request.method == "GET":
            # Listar horarios del espacio
            horarios = espacio.horarios.all().order_by("dia_semana")
            serializer = HorarioEspacioTrabajoListadoSerializer(horarios, many=True)
            return Response(
                {
                    "espacio_id": espacio.id,
                    "espacio_nombre": espacio.nombre,
                    "horarios": serializer.data
                },
                status=status.HTTP_200_OK
            )
        
        elif request.method == "POST":
            # Crear nuevo horario
            context = self.get_serializer_context()
            context["empresa"] = request.tenant
            context["espacio_trabajo"] = espacio
            
            serializer = HorarioEspacioTrabajoCreacionSerializer(
                data=request.data,
                context=context
            )
            serializer.is_valid(raise_exception=True)
            horario = serializer.save()
            
            # AuditorÃ­a: horario creado
            dias = ["Lunes", "Martes", "MiÃ©rcoles", "Jueves", "Viernes", "SÃ¡bado", "Domingo"]
            dia_nombre = dias[horario.dia_semana]
            
            registrar_evento_desde_request(
                request,
                empresa=request.tenant,
                accion=AccionAuditoria.HORARIO_ESPACIO_CREADO,
                usuario=request.user,
                entidad_tipo="HorarioEspacioTrabajo",
                entidad_id=horario.id,
                descripcion=f"Horario creado para espacio '{espacio.nombre}' ({dia_nombre} {horario.hora_inicio}-{horario.hora_fin})",
                metadata={
                    "espacio_id": str(espacio.id),
                    "espacio_nombre": espacio.nombre,
                    "dia_semana": horario.dia_semana,
                    "dia_nombre": dia_nombre,
                    "hora_inicio": str(horario.hora_inicio),
                    "hora_fin": str(horario.hora_fin),
                }
            )
            
            response_serializer = HorarioEspacioTrabajoListadoSerializer(horario)
            return Response(
                {
                    "mensaje": "Horario creado exitosamente",
                    "horario": response_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

    @action(detail=True, methods=["patch"], url_path="editar_horario")
    def editar_horario(self, request, pk=None, **kwargs):
        """
        Editar un horario especÃ­fico.
        PATCH /api/{slug}/espacios/{espacio_id}/editar_horario/{horario_id}/
        
        ParÃ¡metros query: horario_id={horario_id}
        
        Body:
        {
            "dia_semana": 1,
            "hora_inicio": "09:00:00",
            "hora_fin": "18:00:00",
            "activo": true
        }
        """
        horario_id = request.query_params.get('horario_id')
        if not horario_id:
            return Response(
                {"error": "horario_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        horario = get_object_or_404(
            HorarioEspacioTrabajo,
            id=horario_id,
            empresa=request.tenant
        )
        
        # Guardar estado anterior para auditorÃ­a
        datos_anteriores = {
            "dia_semana": horario.dia_semana,
            "hora_inicio": str(horario.hora_inicio),
            "hora_fin": str(horario.hora_fin),
            "activo": horario.activo,
        }
        
        serializer = HorarioEspacioTrabajoEdicionSerializer(
            horario,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        horario = serializer.save()
        
        # Construir cambios para auditorÃ­a
        datos_nuevos = {
            "dia_semana": horario.dia_semana,
            "hora_inicio": str(horario.hora_inicio),
            "hora_fin": str(horario.hora_fin),
            "activo": horario.activo,
        }
        cambios = construir_cambios(datos_anteriores, datos_nuevos)
        
        # AuditorÃ­a: horario actualizado
        dias = ["Lunes", "Martes", "MiÃ©rcoles", "Jueves", "Viernes", "SÃ¡bado", "Domingo"]
        dia_nombre = dias[horario.dia_semana]
        
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.HORARIO_ESPACIO_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="HorarioEspacioTrabajo",
            entidad_id=horario.id,
            descripcion=f"Horario actualizado: {dia_nombre} {horario.hora_inicio}-{horario.hora_fin}",
            metadata=cambios
        )
        
        response_serializer = HorarioEspacioTrabajoListadoSerializer(horario)
        return Response(
            {
                "mensaje": "Horario actualizado exitosamente",
                "horario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="activo_horario")
    def activo_horario(self, request, pk=None, **kwargs):
        """
        Activar o inactivar un horario.
        PATCH /api/{slug}/espacios/{espacio_id}/activo_horario/
        
        ParÃ¡metros query: horario_id={horario_id}
        
        Body:
        {
            "activo": false,
            "motivo": "Horario descontinuado"
        }
        """
        horario_id = request.query_params.get('horario_id')
        if not horario_id:
            return Response(
                {"error": "horario_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        horario = get_object_or_404(
            HorarioEspacioTrabajo,
            id=horario_id,
            empresa=request.tenant
        )
        
        serializer = HorarioEspacioTrabajoActivoSerializer(
            horario,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        
        activo_anterior = horario.activo
        horario = serializer.save()
        
        # AuditorÃ­a: cambio de activo en horario
        motivo = request.data.get("motivo", "")
        dias = ["Lunes", "Martes", "MiÃ©rcoles", "Jueves", "Viernes", "SÃ¡bado", "Domingo"]
        dia_nombre = dias[horario.dia_semana]
        
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.HORARIO_ESPACIO_ACTIVO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="HorarioEspacioTrabajo",
            entidad_id=horario.id,
            descripcion=f"Horario {dia_nombre} cambiÃ³ de {'activo' if activo_anterior else 'inactivo'} a {'activo' if horario.activo else 'inactivo'}",
            metadata={
                "activo_anterior": activo_anterior,
                "activo_nuevo": horario.activo,
                "motivo": motivo,
                "dia_nombre": dia_nombre,
            }
        )
        
        response_serializer = HorarioEspacioTrabajoListadoSerializer(horario)
        return Response(
            {
                "mensaje": f"Horario {'activado' if horario.activo else 'inactivado'} exitosamente",
                "horario": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["delete"], url_path="eliminar_horario")
    def eliminar_horario(self, request, pk=None, **kwargs):
        """
        Eliminar un horario completamente.
        DELETE /api/{slug}/espacios/{espacio_id}/eliminar_horario/
        
        ParÃ¡metros query: horario_id={horario_id}
        """
        horario_id = request.query_params.get('horario_id')
        if not horario_id:
            return Response(
                {"error": "horario_id es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        horario = get_object_or_404(
            HorarioEspacioTrabajo,
            id=horario_id,
            empresa=request.tenant
        )
        
        # Registrar auditorÃ­a antes de eliminar
        dias = ["Lunes", "Martes", "MiÃ©rcoles", "Jueves", "Viernes", "SÃ¡bado", "Domingo"]
        dia_nombre = dias[horario.dia_semana]
        espacio_nombre = horario.espacio_trabajo.nombre
        
        horario_data = {
            "id": str(horario.id),
            "espacio_id": str(horario.espacio_trabajo.id),
            "espacio_nombre": espacio_nombre,
            "dia_semana": horario.dia_semana,
            "dia_nombre": dia_nombre,
            "hora_inicio": str(horario.hora_inicio),
            "hora_fin": str(horario.hora_fin),
            "activo": horario.activo,
        }
        
        # Eliminar horario
        horario.delete()
        
        # AuditorÃ­a: horario eliminado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.HORARIO_ESPACIO_ELIMINADO,
            usuario=request.user,
            entidad_tipo="HorarioEspacioTrabajo",
            entidad_id=horario_data["id"],
            descripcion=f"Horario eliminado: {espacio_nombre} ({dia_nombre} {horario_data['hora_inicio']}-{horario_data['hora_fin']})",
            metadata=horario_data
        )
        
        return Response(
            {"mensaje": "Horario eliminado exitosamente"},
            status=status.HTTP_204_NO_CONTENT
        )

