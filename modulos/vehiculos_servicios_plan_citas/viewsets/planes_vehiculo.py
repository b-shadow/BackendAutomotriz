"""
ViewSet para gestiÃ³n de Planes de VehÃ­culo y sus Detalles (CU22).

Acciones sobre Planes de VehÃ­culo:
- list: Listar planes (filtrado segÃºn rol)
- create: Crear nuevo plan
- retrieve: Obtener detalle de un plan
- partial_update: Editar plan (solo admin/asesor)
- estado: Cambiar estado de plan (solo admin/asesor)

Acciones sobre Detalles del Plan:
- detalles: Listar detalles de un plan
- crear_detalle: Agregar detalle al plan
- editar_detalle: Actualizar detalle (solo admin/asesor)
- estado_detalle: Cambiar estado del detalle (solo admin/asesor)

REGLAS DE NEGOCIO:
1. ADMIN/ASESOR: Ven todos los planes, CRUD completo
2. USUARIO: Solo ven planes de sus vehÃ­culos, pueden agregar detalles como CLIENTE
3. MECÃNICO: Pueden agregar recomendaciones tÃ©cnicas
4. Multi-tenant: Todo filtrado por empresa
5. AuditorÃ­a obligatoria en todas las operaciones
6. Un vehÃ­culo tiene exactamente un plan operativo
"""
import logging
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import transaction

logger = logging.getLogger(__name__)

from modulos.vehiculos_servicios_plan_citas.models import (
    PlanServicioVehiculo,
    PlanServicioDetalle,
    Vehiculo,
    ServicioCatalogo,
    EstadoPlanServicioDetalle,
    EstadoPlanServicioVehiculo,
    OrigenPlanServicioDetalle,
)
from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
    # Plan VehÃ­culo
    PlanServicioVehiculoListadoSerializer,
    PlanServicioVehiculoDetalleSerializer,
    PlanServicioVehiculoCreacionSerializer,
    PlanServicioVehiculoEdicionSerializer,
    PlanServicioVehiculoEstadoSerializer,
    # Detalle Plan
    PlanServicioDetalleListadoSerializer,
    PlanServicioDetalleCreacionSerializer,
    PlanServicioDetalleEdicionSerializer,
    PlanServicioDetalleEstadoSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    registrar_evento_on_commit,
    construir_cambios,
    AccionAuditoria,
)


# ============================================================================
# PERMISOS PERSONALIZADOS
# ============================================================================

class IsAuthenticatedTenant(permissions.BasePermission):
    """Permite acceso a usuarios autenticados del tenant actual."""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        return True


class PuedeGestionarPlanesVehiculo(permissions.BasePermission):
    """Permite crear y editar planes solo a ADMIN y ASESOR DE SERVICIO."""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]


class PuedeVerPlanVehiculo(permissions.BasePermission):
    """Controla acceso a lectura de planes. Clientes solo ven sus vehÃ­culos."""
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        
        # Cliente solo ve planes de sus vehÃ­culos
        if rol_nombre == "USUARIO":
            return obj.vehiculo.propietario == request.user
        
        # Admin y asesor ven todos
        return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]


class PuedeAgregarDetalles(permissions.BasePermission):
    """Controla quiÃ©nes pueden agregar detalles a planes."""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        # Solo ADMIN, ASESOR, USUARIO y MECÃNICO pueden agregar detalles
        roles_permitidos = ["ADMIN", "ASESOR DE SERVICIO", "USUARIO", "MECÃNICO"]
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in roles_permitidos


class PuedeGestionarDetalles(permissions.BasePermission):
    """Solo ADMIN y ASESOR DE SERVICIO pueden editar y cambiar estado de detalles."""
    
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]


# ============================================================================
# VIEWSET DE PLANES DE VEHÃCULOS
# ============================================================================

class PlanesVehiculoViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestiÃ³n de planes de vehÃ­culos dentro de una empresa tenant.
    
    CU22 - NUEVA REGLA (VersiÃ³n 2):
    - Los planes se crean automÃ¡ticamente cuando se registra un vehÃ­culo
    - NO se pueden crear nuevos planes manualmente desde este mÃ³dulo
    - Solo se gestionan los DETALLES del plan (agregar, editar, eliminar)
    
    ENDPOINTS:
    GET /api/{slug}/planes-vehiculo/ - Listar planes
    POST /api/{slug}/planes-vehiculo/ - âŒ DESHABILITADO (retorna 403)
    GET /api/{slug}/planes-vehiculo/{id}/ - Detalle plan
    PATCH /api/{slug}/planes-vehiculo/{id}/ - Editar plan (solo ADMIN/ASESOR)
    PATCH /api/{slug}/planes-vehiculo/{id}/estado/ - Cambiar estado (solo ADMIN/ASESOR)
    GET /api/{slug}/planes-vehiculo/{id}/detalles/ - Listar detalles del plan
    POST /api/{slug}/planes-vehiculo/{id}/crear-detalle/ - Agregar detalle
    PATCH /api/{slug}/planes-vehiculo/detalles/{detalle_id}/editar/ - Editar detalle (solo ADMIN/ASESOR)
    PATCH /api/{slug}/planes-vehiculo/detalles/{detalle_id}/estado/ - Cambiar estado de detalle (solo ADMIN/ASESOR)
    DELETE /api/{slug}/planes-vehiculo/detalles/{detalle_id}/ - Eliminar detalle (solo ADMIN/ASESOR)
    
    REGLAS DE NEGOCIO:
    1. ADMIN/ASESOR: Ven todos los planes, CRUD completo de detalles
    2. USUARIO: Solo ven planes de sus vehÃ­culos, pueden agregar detalles como CLIENTE
    3. MECÃNICO: Pueden agregar recomendaciones tÃ©cnicas
    4. Multi-tenant: Todo filtrado por empresa
    5. AuditorÃ­a obligatoria en todas las operaciones
    6. Un vehÃ­culo tiene exactamente un plan operativo
    """
    
    serializer_class = PlanServicioVehiculoDetalleSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["vehiculo__placa", "vehiculo__marca", "vehiculo__modelo"]
    ordering_fields = ["created_at", "updated_at", "estado"]
    ordering = ["-created_at"]
    filterset_fields = ["estado", "vehiculo__id"]

    def get_queryset(self):
        """
        Filtrar planes por empresa del tenant.
        
        ADMIN y ASESOR: Ven todos los planes
        USUARIO: Solo ve planes de sus vehÃ­culos
        MECÃNICO: Ven planes de vehÃ­culos en su Ã¡mbito (se podrÃ­a refinar luego)
        """
        if not hasattr(self.request, "tenant"):
            return PlanServicioVehiculo.objects.none()
        
        queryset = PlanServicioVehiculo.objects.filter(empresa=self.request.tenant)
        
        rol_nombre = self.request.user.rol.nombre if self.request.user.rol else None
        
        # Usuario solo ve planes de sus vehÃ­culos
        if rol_nombre == "USUARIO":
            queryset = queryset.filter(vehiculo__propietario=self.request.user)
        
        return queryset.select_related("vehiculo", "creado_por", "empresa").prefetch_related("detalles")

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action == "list":
            return PlanServicioVehiculoListadoSerializer
        elif self.action == "create":
            return PlanServicioVehiculoCreacionSerializer
        elif self.action == "estado":
            return PlanServicioVehiculoEstadoSerializer
        elif self.action in ["update", "partial_update"]:
            return PlanServicioVehiculoEdicionSerializer
        elif self.action == "detalles":
            return PlanServicioDetalleListadoSerializer
        return PlanServicioVehiculoDetalleSerializer

    def get_permissions(self):
        """Asignar permisos segÃºn la acciÃ³n."""
        if self.action in ["list", "retrieve"]:
            # list: AUTENTICADOS (filtrado por rol en queryset)
            # retrieve: AUTENTICADOS (validado en check_object_permissions)
            permission_classes = [IsAuthenticatedTenant]
        elif self.action == "create":
            # Crear plan: ADMIN, ASESOR, USUARIO (validado que sea su vehÃ­culo en create())
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["update", "partial_update", "estado"]:
            # Editar/cambiar estado plan: solo ADMIN y ASESOR
            permission_classes = [PuedeGestionarPlanesVehiculo]
        elif self.action == "detalles":
            # Listar detalles: AUTENTICADOS
            permission_classes = [IsAuthenticatedTenant]
        elif self.action == "crear_detalle":
            # Agregar detalle: ADMIN, ASESOR, USUARIO, MECÃNICO
            # pero validado en el mÃ©todo que USUARIO solo CLIENTE, MECÃNICO solo MECANICO
            permission_classes = [PuedeAgregarDetalles]
        elif self.action in ["editar_detalle", "estado_detalle", "delete_detalle"]:
            # Editar, cambiar estado y ELIMINAR detalle: solo ADMIN y ASESOR
            permission_classes = [PuedeGestionarDetalles]
        else:
            permission_classes = [IsAuthenticatedTenant]
        
        return [permission() for permission in permission_classes]

    def get_serializer_context(self):
        """Agregar empresa y usuario autenticado al contexto."""
        context = super().get_serializer_context()
        context["empresa"] = getattr(self.request, "tenant", None)
        context["usuario_autenticado"] = self.request.user
        return context

    def check_object_permissions(self, request, obj):
        """Verificar permisos de objeto para retrieve y update."""
        if self.action == "retrieve":
            rol_nombre = request.user.rol.nombre if request.user.rol else None
            if rol_nombre == "USUARIO" and obj.vehiculo.propietario != request.user:
                self.permission_denied(
                    request,
                    message="No tienes permiso para ver este plan de vehÃ­culo."
                )
        super().check_object_permissions(request, obj)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """
        DESHABILITADO (CU22 - Nueva Regla):
        No se pueden crear nuevos planes manualmente desde este mÃ³dulo.
        
        El plan de vehÃ­culo se crea automÃ¡ticamente cuando se registra el vehÃ­culo
        con estado LIBRE y sin detalles.
        
        Solo se gestionan los DETALLES del plan (agregar, editar, eliminar).
        
        POST /api/{slug}/planes-vehiculo/
        â†’ Retorna 403 con mensaje claro
        """
        return Response(
            {
                "error": "No se pueden crear nuevos planes manualmente.",
                "detalle": "El plan de vehÃ­culo se crea automÃ¡ticamente al registrar el vehÃ­culo. "
                           "Solo se pueden gestionar los detalles del plan (agregar, editar, eliminar).",
                "accion": "Para crear un plan, primero registra un vehÃ­culo en /api/{slug}/vehiculos/"
            },
            status=status.HTTP_403_FORBIDDEN
        )

    @transaction.atomic
    def partial_update(self, request, *args, **kwargs):
        """
        Editar plan de vehÃ­culo (solo admin/asesor).
        
        PATCH /api/{slug}/planes-vehiculo/{id}/
        Body:
        {
            "descripcion_general": "Nueva descripciÃ³n"
        }
        
        Validaciones:
        - El plan siempre es editable
        """
        plan = self.get_object()
        
        old_data = {
            "descripcion_general": plan.descripcion_general,
        }
        
        serializer = self.get_serializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        
        new_data = {
            "descripcion_general": plan.descripcion_general,
        }
        
        cambios = construir_cambios(old_data, new_data)
        
        # Registrar auditorÃ­a
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="PlanServicioVehiculo",
            entidad_id=plan.id,
            descripcion=f"Plan de vehÃ­culo actualizado ({plan.vehiculo.placa})",
            metadata=cambios
        )
        
        # Devolver respuesta rica
        response_serializer = PlanServicioVehiculoDetalleSerializer(plan)
        return Response(
            {
                "mensaje": "Plan actualizado exitosamente",
                "plan": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="estado")
    @transaction.atomic
    def estado(self, request, pk=None, empresa_slug=None):
        """
        Cambiar estado de un plan de vehÃ­culo.
        
        PATCH /api/{slug}/planes-vehiculo/{id}/estado/
        Body:
        {
            "estado": "PROGRAMADO",
            "motivo": "Servicios programados en cita"
        }
        
        Validaciones:
        - Un plan CERRADO no puede cambiar de estado
        - Solo admin/asesor pueden cambiar estado
        """
        plan = self.get_object()
        old_estado = plan.estado
        
        # El plan siempre es editable en sus estados LIBRE o EN_EJECUCION
        from modulos.vehiculos_servicios_plan_citas.models import EstadoPlanServicioVehiculo
        
        nuevo_estado = request.data.get("estado")
        
        serializer = self.get_serializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        
        motivo = request.data.get("motivo", "")
        
        # Registrar auditorÃ­a
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_ESTADO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="PlanServicioVehiculo",
            entidad_id=plan.id,
            descripcion=f"Estado de plan cambiado de {old_estado} a {plan.estado}",
            metadata={
                "vehiculo_placa": plan.vehiculo.placa,
                "estado_anterior": old_estado,
                "estado_nuevo": plan.estado,
                "motivo": motivo,
            }
        )
        
        # Devolver respuesta rica
        response_serializer = PlanServicioVehiculoDetalleSerializer(plan)
        return Response(
            {
                "mensaje": f"Estado del plan cambiado a {plan.estado} exitosamente",
                "plan": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["get"], url_path="detalles")
    def detalles(self, request, pk=None, empresa_slug=None):
        """
        Listar detalles de un plan de vehÃ­culo.
        
        GET /api/{slug}/planes-vehiculo/{id}/detalles/
        """
        plan = self.get_object()
        detalles = plan.detalles.all().order_by("prioridad", "-created_at")
        
        serializer = self.get_serializer(detalles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="crear-detalle")
    @transaction.atomic
    def crear_detalle(self, request, pk=None, empresa_slug=None):
        """
        Agregar un nuevo detalle al plan.
        
        POST /api/{slug}/planes-vehiculo/{id}/crear-detalle/
        Body:
        {
            "servicio_catalogo_id": "uuid-servicio",
            "prioridad": "BAJA|MEDIA|ALTA|URGENTE",
            "observaciones": "DescripciÃ³n del detalle"
        }
        
        NUEVO FLUJO (CU22 - CatÃ¡logo Obligatorio):
        - servicio_catalogo_id es OBLIGATORIO
        - origen se detecta automÃ¡ticamente desde request.user.rol.nombre:
          * USUARIO â†’ CLIENTE
          * MECÃNICO â†’ MECANICO
          * ADMIN/ASESOR â†’ ASESOR
        - tiempo_estandar_min y precio_referencial se obtienen del servicio catÃ¡logo
        - estado inicial se asigna automÃ¡ticamente:
          * MECANICO â†’ RECOMENDADO
          * CLIENTE/ASESOR â†’ PENDIENTE
        - recomendado_por se asigna al usuario si origen es MECANICO
        
        El frontend NO debe enviar: origen, tiempo_estandar_min, precio_referencial
        (estos valores se determinan automÃ¡ticamente en el backend)
        """
        plan = self.get_object()
        
        # Preparar datos para serializer
        data = request.data.copy()
        data["plan_servicio_id"] = plan.id
        
        serializer = PlanServicioDetalleCreacionSerializer(
            data=data,
            context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        detalle = serializer.save()
        
        # Registrar auditorÃ­a
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_DETALLE_CREADO,
            usuario=request.user,
            entidad_tipo="PlanServicioDetalle",
            entidad_id=detalle.id,
            descripcion=f"Detalle agregado al plan de {plan.vehiculo.placa}",
            metadata={
                "plan_id": str(plan.id),
                "vehiculo_placa": plan.vehiculo.placa,
                "servicio": detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else "S/C",
                "origen": detalle.origen,
                "prioridad": detalle.prioridad,
                "estado": detalle.estado,
            }
        )
        
        response_serializer = PlanServicioDetalleListadoSerializer(detalle)
        return Response(
            {
                "mensaje": f"Detalle agregado como {detalle.origen.lower()} exitosamente",
                "detalle": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["patch"], url_path="detalles/(P<detalle_id>[^/.]+)/editar")
    @transaction.atomic
    def editar_detalle(self, request, pk=None, detalle_id=None, empresa_slug=None):
        """
        Editar un detalle especÃ­fico del plan.
        
        PATCH /api/{slug}/planes-vehiculo/detalles/{detalle_id}/editar/
        Body:
        {
            "prioridad": "ALTA",
            "observaciones": "Nueva observaciÃ³n",
            "tiempo_estandar_min": 90,
            "precio_referencial": 200.00
        }
        
        Permisos: Solo ADMIN y ASESOR DE SERVICIO
        Restricciones:
        - No se puede editar un detalle si estÃ¡ FINALIZADO o INNECESARIO
        """
        detalle = get_object_or_404(
            PlanServicioDetalle,
            id=detalle_id,
            empresa=request.tenant
        )
        
        # ValidaciÃ³n: no editar detalles finalizados
        if detalle.estado in ["FINALIZADO", "INNECESARIO"]:
            return Response(
                {"error": f"No se puede editar un detalle que estÃ¡ {detalle.estado.lower()}."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        old_data = {
            "prioridad": detalle.prioridad,
            "observaciones": detalle.observaciones,
            "tiempo_estandar_min": detalle.tiempo_estandar_min,
            "precio_referencial": float(detalle.precio_referencial),
        }
        
        serializer = PlanServicioDetalleEdicionSerializer(
            detalle,
            data=request.data,
            partial=True,
            context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        detalle = serializer.save()
        
        new_data = {
            "prioridad": detalle.prioridad,
            "observaciones": detalle.observaciones,
            "tiempo_estandar_min": detalle.tiempo_estandar_min,
            "precio_referencial": float(detalle.precio_referencial),
        }
        
        cambios = construir_cambios(old_data, new_data)
        
        # Registrar auditorÃ­a
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_DETALLE_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="PlanServicioDetalle",
            entidad_id=detalle.id,
            descripcion=f"Detalle del plan actualizado",
            metadata=cambios
        )
        
        response_serializer = PlanServicioDetalleListadoSerializer(detalle)
        return Response(
            {
                "mensaje": "Detalle actualizado exitosamente",
                "detalle": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["patch"], url_path="detalles/(P<detalle_id>[^/.]+)/estado")
    @transaction.atomic
    def estado_detalle(self, request, pk=None, detalle_id=None, empresa_slug=None):
        """
        Cambiar estado de un detalle del plan.
        
        PATCH /api/{slug}/planes-vehiculo/detalles/{detalle_id}/estado/
        Body:
        {
            "estado": "PROGRAMADO|EN_PROCESO|FINALIZADO|INNECESARIO|DIFERIDO",
            "motivo": "Motivo del cambio"
        }
        
        Permisos: Solo ADMIN y ASESOR DE SERVICIO
        
        Transiciones vÃ¡lidas mÃ­nimas:
        - PENDIENTE/RECOMENDADO â†’ PROGRAMADO â†’ EN_PROCESO â†’ FINALIZADO
        - Cualquier estado â†’ INNECESARIO (rechazo)
        - Cualquier estado â†’ DIFERIDO (posposiciÃ³n)
        - FINALIZADO â†’ no cambiar (terminal)
        """
        detalle = get_object_or_404(
            PlanServicioDetalle,
            id=detalle_id,
            empresa=request.tenant
        )
        
        old_estado = detalle.estado
        nuevo_estado = request.data.get("estado")
        
        # ValidaciÃ³n: FINALIZADO es estado terminal
        if detalle.estado == "FINALIZADO":
            return Response(
                {"error": "Un detalle finalizado no puede cambiar de estado."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ValidaciÃ³n: INNECESARIO es estado terminal
        if detalle.estado == "INNECESARIO" and nuevo_estado != "INNECESARIO":
            return Response(
                {"error": "Un detalle marcado como innecesario no puede cambiar de estado."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = PlanServicioDetalleEstadoSerializer(
            detalle,
            data=request.data,
            partial=True,
            context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        detalle = serializer.save()
        
        motivo = request.data.get("motivo", "")
        
        # Registrar auditorÃ­a
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_DETALLE_ESTADO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="PlanServicioDetalle",
            entidad_id=detalle.id,
            descripcion=f"Estado de detalle cambiado de {old_estado} a {detalle.estado}",
            metadata={
                "estado_anterior": old_estado,
                "estado_nuevo": detalle.estado,
                "motivo": motivo,
                "servicio": detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else "S/C",
            }
        )
        
        response_serializer = PlanServicioDetalleListadoSerializer(detalle)
        return Response(
            {
                "mensaje": f"Estado del detalle cambiado a {detalle.estado.lower()} exitosamente",
                "detalle": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=False, methods=["delete"], url_path="detalles/(P<detalle_id>[^/.]+)")
    @transaction.atomic
    def delete_detalle(self, request, pk=None, detalle_id=None, empresa_slug=None):
        """
        Eliminar un detalle del plan de vehÃ­culo.
        
        DELETE /api/{slug}/planes-vehiculo/detalles/{detalle_id}/
        
        CU22 - Nueva Regla:
        - Los detalles pueden quitarse manualmente si no estÃ¡n siendo usados
        - Restricciones:
          * No se pueden eliminar detalles en estado FINALIZADO o EN_PROCESO
          * Detalles sin usar (PENDIENTE, RECOMENDADO, DIFERIDO) sÃ­ se pueden eliminar
          * Solo ADMIN y ASESOR DE SERVICIO pueden eliminar
        
        El detalle se elimina de la base de datos y se registra en auditorÃ­a.
        """
        detalle = get_object_or_404(
            PlanServicioDetalle,
            id=detalle_id,
            empresa=request.tenant
        )
        
        # ValidaciÃ³n: no eliminar detalles en uso
        estados_no_eliminables = ["FINALIZADO", "EN_PROCESO"]
        if detalle.estado in estados_no_eliminables:
            return Response(
                {
                    "error": f"No se puede eliminar un detalle que estÃ¡ en estado {detalle.estado.lower()}.",
                    "detalle": "Solo se pueden eliminar detalles sin usar (PENDIENTE, RECOMENDADO, DIFERIDO, INNECESARIO).",
                    "estado_actual": detalle.estado,
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Obtener informaciÃ³n para auditorÃ­a antes de eliminar
        plan_id = detalle.plan_servicio.id
        vehiculo_placa = detalle.plan_servicio.vehiculo.placa
        servicio_nombre = detalle.servicio_catalogo.nombre if detalle.servicio_catalogo else "S/C"
        detalle_estado = detalle.estado
        detalle_id_str = str(detalle.id)
        
        # Eliminar el detalle
        detalle.delete()
        
        # Registrar auditorÃ­a de eliminaciÃ³n
        registrar_evento_desde_request(
            request=request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_DETALLE_ELIMINADO,
            usuario=request.user,
            entidad_tipo="PlanServicioDetalle",
            entidad_id=detalle_id_str,
            descripcion=f"Detalle eliminado del plan de {vehiculo_placa}",
            metadata={
                "plan_id": str(plan_id),
                "vehiculo_placa": vehiculo_placa,
                "servicio": servicio_nombre,
                "estado_al_eliminar": detalle_estado,
            }
        )
        
        return Response(
            {
                "mensaje": "Detalle eliminado exitosamente",
                "detalle_eliminado": {
                    "id": detalle_id_str,
                    "servicio": servicio_nombre,
                    "estado": detalle_estado,
                }
            },
            status=status.HTTP_200_OK
        )

