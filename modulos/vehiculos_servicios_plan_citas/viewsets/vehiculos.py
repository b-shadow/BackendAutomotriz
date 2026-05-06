""" ViewSet para gestiÃ³n de vehÃ­culos en contexto multi-tenant. """
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import transaction

from modulos.vehiculos_servicios_plan_citas.models import Vehiculo, Usuario, PlanServicioVehiculo, EstadoPlanServicioVehiculo
from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
    VehiculoListadoSerializer,
    VehiculoDetalleSerializer,
    VehiculoCreacionSerializer,
    VehiculoEdicionSerializer,
    VehiculoEstadoSerializer,
)
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_desde_request,
    registrar_evento_on_commit,
    construir_cambios,
    AccionAuditoria,
)
# PERMISOS PERSONALIZADOS
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

class PuedeGestionarVehiculos(permissions.BasePermission):
    """ Permite crear y editar vehÃ­culos solo a asesor de servicio y admin. """
    def has_permission(self, request, view):
        # El usuario debe estar autenticado y en el tenant
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        # El usuario debe tener rol ASESOR DE SERVICIO o ADMIN
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]

class PuedeVerVehiculos(permissions.BasePermission):
    """ Controla acceso a lectura de vehÃ­culos. """
    def has_object_permission(self, request, view, obj):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False     
        # Cliente solo ve sus vehÃ­culos
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        if rol_nombre == "USUARIO":
            return obj.propietario == request.user
        # Asesor de servicio y admin ven todos
        return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]

class PuedeEditarVehiculos(permissions.BasePermission):
    """ Solo asesor de servicio y admin pueden editar vehÃ­culos. """
    def has_object_permission(self, request, view, obj):
        # El usuario debe estar autenticado
        if not request.user or not request.user.is_authenticated:
            return False
        # Solo asesor de servicio y admin
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]

# VIEWSET DE VEHÃCULOS
class VehiculosViewSet(viewsets.ModelViewSet):
    """ ViewSet para gestiÃ³n de vehÃ­culos dentro de una empresa tenant. """
    serializer_class = VehiculoDetalleSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["placa", "marca", "modelo"]
    ordering_fields = ["placa", "marca", "created_at"]
    ordering = ["-created_at"]
    filterset_fields = ["estado", "propietario"]

    def get_queryset(self):
        """ Filtrar vehÃ­culos por empresa del tenant. """
        if not hasattr(self.request, "tenant"):
            return Vehiculo.objects.none()
        queryset = Vehiculo.objects.filter(empresa=self.request.tenant)
        # Filtrado segÃºn rol
        rol_nombre = self.request.user.rol.nombre if self.request.user.rol else None
        if rol_nombre == "USUARIO":
            queryset = queryset.filter(propietario=self.request.user)
        return queryset.select_related("propietario", "empresa")

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action in ["list", "retrieve"]:
            # âœ… Usar VehiculoListadoSerializer para list Y retrieve
            # Esto asegura que propietario se devuelva como objeto anidado
            return VehiculoListadoSerializer
        elif self.action == "create":
            return VehiculoCreacionSerializer
        elif self.action == "estado":
            return VehiculoEstadoSerializer
        elif self.action in ["update", "partial_update"]:
            return VehiculoEdicionSerializer
        return VehiculoListadoSerializer

    def get_permissions(self):
        """ Asignar permisos segÃºn la acciÃ³n. """
        if self.action in ["list", "retrieve"]:
            # list: todos autenticados (filtrado por queryset segÃºn rol)
            # retrieve: validado por PuedeVerVehiculos
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["create"]:
            # Crear: cliente puede crear (solo el suyo), asesor/admin tambiÃ©n crean
            permission_classes = [IsAuthenticatedTenant]
        elif self.action in ["update", "partial_update", "estado"]:
            # Solo asesor/admin
            permission_classes = [PuedeGestionarVehiculos]
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
        """ Verificar permisos de objeto. Para retrieve, validar que el cliente solo vea sus vehÃ­culos. """
        if self.action == "retrieve":
            rol_nombre = request.user.rol.nombre if request.user.rol else None
            if rol_nombre == "USUARIO" and obj.propietario != request.user:
                self.permission_denied(
                    request,
                    message="No tienes permiso para ver este vehÃ­culo."
                )
        super().check_object_permissions(request, obj)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """ Crear un nuevo vehÃ­culo.
        POST /api/{slug}/vehiculos/
        Body (cliente):
        {
            "placa": "ABC123",
            "marca": "Toyota",
            "modelo": "Corolla",
            "anio": 2023,
            "color": "Blanco",
            "kilometraje_actual": 500,
            "vin_chasis": "XXXXXX",
            "motor": "1.8L",
            "observaciones": ""
        }   
        Body (asesor/admin):
        {
            "propietario_id": "uuid-del-propietario",
            "placa": "ABC123",
            ... resto de campos
        }
        
        NUEVO FLUJO (CU22):
        - Al crear el vehÃ­culo, se crea automÃ¡ticamente su PlanServicioVehiculo:
          * estado = LIBRE
          * creado_por = request.user
        - Todo en una transacciÃ³n atÃ³mica
        - AuditorÃ­a registra ambos eventos
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        # AuditorÃ­a: vehÃ­culo creado
        vehiculo = serializer.instance
        propietario_nombres = vehiculo.propietario.nombres if vehiculo.propietario else "Sin propietario"
        
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.VEHICULO_CREADO,
            usuario=request.user,
            entidad_tipo="Vehiculo",
            entidad_id=vehiculo.id,
            descripcion=f"VehÃ­culo {vehiculo.marca} {vehiculo.modelo} ({vehiculo.placa}) creado para {propietario_nombres}",
            metadata={
                "placa": vehiculo.placa,
                "marca": vehiculo.marca,
                "modelo": vehiculo.modelo,
                "anio": vehiculo.anio,
                "propietario_id": str(vehiculo.propietario.id) if vehiculo.propietario else None,
                "propietario_email": vehiculo.propietario.email if vehiculo.propietario else None,
            }
        )
        
        # AUTO-CREAR PLAN DE VEHÃCULO (CU22)
        plan = PlanServicioVehiculo.objects.create(
            empresa=request.tenant,
            vehiculo=vehiculo,
            estado=EstadoPlanServicioVehiculo.LIBRE,
            creado_por=request.user,
        )
        
        # Registrar auditorÃ­a de creaciÃ³n automÃ¡tica del plan
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.PLAN_VEHICULO_CREADO,
            usuario=request.user,
            entidad_tipo="PlanServicioVehiculo",
            entidad_id=plan.id,
            descripcion=f"Plan de vehÃ­culo creado automÃ¡ticamente para {vehiculo.placa}",
            metadata={
                "vehiculo_id": str(vehiculo.id),
                "vehiculo_placa": vehiculo.placa,
                "creacion_automatica": True,
            }
        )
        
        # Retornar con serializer de detalle
        response_serializer = VehiculoDetalleSerializer(vehiculo, context=self.get_serializer_context())
        return Response(
            {
                "mensaje": "VehÃ­culo creado exitosamente",
                "vehiculo": response_serializer.data
            },
            status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        """ Editar parcialmente un vehÃ­culo (solo asesor/admin). """
        vehiculo = self.get_object()
        # Guardar estado anterior para auditorÃ­a
        datos_anteriores = {
            "marca": vehiculo.marca,
            "modelo": vehiculo.modelo,
            "anio": vehiculo.anio,
            "color": vehiculo.color,
            "kilometraje_actual": vehiculo.kilometraje_actual,
            "vin_chasis": vehiculo.vin_chasis,
            "motor": vehiculo.motor,
            "observaciones": vehiculo.observaciones,
            "propietario_id": str(vehiculo.propietario.id) if vehiculo.propietario else None,
        }
        serializer = self.get_serializer(vehiculo, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Construir cambios para auditorÃ­a
        datos_nuevos = {
            "marca": vehiculo.marca,
            "modelo": vehiculo.modelo,
            "anio": vehiculo.anio,
            "color": vehiculo.color,
            "kilometraje_actual": vehiculo.kilometraje_actual,
            "vin_chasis": vehiculo.vin_chasis,
            "motor": vehiculo.motor,
            "observaciones": vehiculo.observaciones,
            "propietario_id": str(vehiculo.propietario.id) if vehiculo.propietario else None,
        }
        cambios = construir_cambios(datos_anteriores, datos_nuevos)
        # AuditorÃ­a: vehÃ­culo actualizado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.VEHICULO_ACTUALIZADO,
            usuario=request.user,
            entidad_tipo="Vehiculo",
            entidad_id=vehiculo.id,
            descripcion=f"VehÃ­culo {vehiculo.marca} {vehiculo.modelo} ({vehiculo.placa}) actualizado",
            metadata=cambios
        )
        response_serializer = VehiculoDetalleSerializer(vehiculo, context=self.get_serializer_context())
        return Response(
            {
                "mensaje": "VehÃ­culo actualizado exitosamente",
                "vehiculo": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["patch"], url_path="estado")
    def estado(self, request, pk=None, **kwargs):
        """ Cambiar el estado de un vehÃ­culo (activar/inactivar). """
        vehiculo = self.get_object()
        # Verificar permisos
        if not request.user.rol or request.user.rol.nombre not in ["ASESOR DE SERVICIO", "ADMIN"]:
            return Response(
                {"error": "Only ASESOR DE SERVICIO or ADMIN can change vehicle status."},
                status=status.HTTP_403_FORBIDDEN
            )
        # Guardar estado anterior
        estado_anterior = vehiculo.estado
        serializer = self.get_serializer(vehiculo, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        # Obtener motivo si lo proporcionÃ³
        motivo = request.data.get("motivo", "")
        # AuditorÃ­a: estado cambiado
        registrar_evento_desde_request(
            request,
            empresa=request.tenant,
            accion=AccionAuditoria.VEHICULO_ESTADO_CAMBIADO,
            usuario=request.user,
            entidad_tipo="Vehiculo",
            entidad_id=vehiculo.id,
            descripcion=f"Estado del vehÃ­culo {vehiculo.marca} {vehiculo.modelo} ({vehiculo.placa}) cambiÃ³ de {estado_anterior} a {vehiculo.estado}",
            metadata={
                "estado_anterior": estado_anterior,
                "estado_nuevo": vehiculo.estado,
                "motivo": motivo,
            }
        )
        response_serializer = VehiculoDetalleSerializer(vehiculo, context=self.get_serializer_context())
        return Response(
            {
                "mensaje": f"Estado del vehÃ­culo cambiado a {vehiculo.estado}",
                "vehiculo": response_serializer.data
            },
            status=status.HTTP_200_OK
        )

