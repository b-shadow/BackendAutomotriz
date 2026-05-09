"""
ViewSet para gestiÃ³n de citas en contexto multi-tenant.
Implementa CU18: Gestionar cita.

Funcionalidades:
- Crear cita con detalles y espacios
- Listar citas
- Ver detalle de cita
- Editar cita (fecha, hora, espacios, detalles)
- Cancelar cita
- Reprogramar cita
"""
from rest_framework import viewsets, status, permissions, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from modulos.vehiculos_servicios_plan_citas.models import (
    Cita,
    CitaDetalle,
    CitaEspacioSegmento,
    Vehiculo,
    Usuario,
    PlanServicioVehiculo,
    PlanServicioDetalle,
    EstadoCita,
    EstadoPlanServicioDetalle,
    EspacioTrabajo,
    HorarioEspacioTrabajo,
)
from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
    CitaListadoSerializer,
    CitaDetalleSerializer,
    CitaCreacionSerializer,
    CitaEdicionSerializer,
    CitaCancelacionSerializer,
    CitaDetalleIndividualSerializer,
    CitaEspacioSegmentoSerializer,
    CitaEspacioSegmentoCreacionSerializer,
    CitaPreviewIntencionSerializer,
    validar_conflictos_espacios_en_bd,
)
from modulos.vehiculos_servicios_plan_citas.services import CitasProgramacionService
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
    """
    Permite acceso a cualquier usuario autenticado del tenant actual.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        return True


class PuedeGestionarCitas(permissions.BasePermission):
    """
    Permite crear y editar citas solo a asesor de servicio, admin y clientes.
    - ADMIN: puede gestionar todas las citas
    - ASESOR DE SERVICIO: puede crear y gestionar todas las citas
    - USUARIO (cliente): solo puede crear/ver sus propias citas
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        
        # Permisos por acciÃ³n
        if view.action in ["create", "update", "partial_update", "destroy", 
                          "cancelar", "reprogramar"]:
            return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN", "USUARIO"]
        
        # Para lectura, todos pueden ver sus propias citas
        return True


class PuedeVerCita(permissions.BasePermission):
    """
    Control de acceso a lectura de citas.
    - Cliente solo ve sus citas (donde es cliente)
    - Asesor/Admin ven todas
    - Bloquea roles no operativos a nivel de colecciÃ³n (list)
    """
    def has_permission(self, request, view):
        """Permiso a nivel de colecciÃ³n - restringe list para roles no operativos."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        # Solo permitir list/retrieve para ADMIN, ASESOR DE SERVICIO, USUARIO
        # Bloquear MECÃNICO, ADMINISTRATIVO, ALMACENERO
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        allowed_roles = ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"]
        
        return rol_nombre in allowed_roles
    
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        
        if rol_nombre == "USUARIO":
            # Cliente solo ve citas donde es cliente
            return obj.cliente == request.user
        
        # Asesor de servicio y admin ven todas
        return rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]


class PuedeEditarCita(permissions.BasePermission):
    """
    Solo asesor de servicio, admin y el cliente (antes de ingreso) pueden editar.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        
        # Asesor y admin siempre pueden editar
        if rol_nombre in ["ASESOR DE SERVICIO", "ADMIN"]:
            return True
        
        # Cliente solo puede editar si es la cita suya y estÃ¡ PROGRAMADA
        if rol_nombre == "USUARIO":
            if obj.cliente != request.user:
                return False
            # Solo editable si estÃ¡ programada (antes de ingreso)
            return obj.estado == EstadoCita.PROGRAMADA
        
        return False


class PuedeUsarRecepcionMinima(permissions.BasePermission):
    """
    Solo ADMIN o ASESOR DE SERVICIO pueden usar funciones de CU21 (recepciÃ³n mÃ­nima).
    Bloquea roles como USUARIO, MECÃNICO, ADMINISTRATIVO, ALMACENERO.
    """
    def has_permission(self, request, view):
        """ValidaciÃ³n a nivel de colecciÃ³n (para detail=False)."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]
    
    def has_object_permission(self, request, view, obj):
        """ValidaciÃ³n a nivel de objeto (para detail=True)."""
        if not request.user or not request.user.is_authenticated:
            return False
        
        rol_nombre = request.user.rol.nombre if request.user.rol else None
        return rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]


# ============================================================================
# VIEWSET DE CITAS
# ============================================================================

class CitasViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestiÃ³n de citas en contexto multi-tenant.
    
    Acciones disponibles:
    - list: Listar citas del tenant
    - create: Crear nueva cita
    - retrieve: Ver detalle de cita
    - update/partial_update: Editar cita
    - destroy: BLOQUEADO - Usar cancelar en su lugar
    - cancelar: CUSTOM - Cancelar cita creando registro de cancellaciÃ³n
    - reprogramar: CUSTOM - Crear nueva cita basada en la anterior
    """
    serializer_class = CitaDetalleSerializer
    permission_classes = [IsAuthenticatedTenant]
    filter_backends = [SearchFilter, OrderingFilter, DjangoFilterBackend]
    search_fields = ["vehiculo__placa", "cliente__nombres", "cliente__email"]
    ordering_fields = ["fecha_hora_inicio_programada", "estado", "created_at"]
    ordering = ["-fecha_hora_inicio_programada"]
    filterset_fields = ["estado", "cliente", "vehiculo", "canal_origen"]
    NO_SHOW_TOLERANCIA_MIN = 15

    def get_permissions(self):
        """Aplicar permisos especÃ­ficos segÃºn la acciÃ³n."""
        if self.action == "list" or self.action == "retrieve":
            # Listar y ver: IsAuthenticatedTenant + PuedeVerCita (object-level)
            return [IsAuthenticatedTenant(), PuedeVerCita()]
        elif self.action in ["create", "update", "partial_update", "marcar_no_show"]:
            # Crear y editar: IsAuthenticatedTenant + PuedeGestionarCitas
            return [IsAuthenticatedTenant(), PuedeGestionarCitas()]
        elif self.action == "bloques_disponibles":
            # Consulta operativa para creación de citas
            return [IsAuthenticatedTenant(), PuedeGestionarCitas()]
        elif self.action == "agenda":
            return [IsAuthenticatedTenant(), PuedeVerCita()]
        elif self.action == "destroy":
            # Destroy bloqueado (ver mÃ©todo override)
            return [IsAuthenticatedTenant()]
        elif self.action == "cancelar":
            # Cancelar: IsAuthenticatedTenant + PuedeEditarCita
            return [IsAuthenticatedTenant(), PuedeEditarCita()]
        elif self.action == "reprogramar":
            # Reprogramar: IsAuthenticatedTenant + PuedeGestionarCitas
            return [IsAuthenticatedTenant(), PuedeGestionarCitas()]
        elif self.action in [
            "recepcion_operativa", 
            "recepcion_detalle", 
            "registrar_llegada",
            "ajustar_servicios_recepcion",
            "marcar_en_proceso",
            "marcar_vehiculo_devuelto"
        ]:
            # CU21 - ADMIN o ASESOR DE SERVICIO Ãºnicamente
            return [IsAuthenticatedTenant(), PuedeUsarRecepcionMinima()]
        # Default
        return [IsAuthenticatedTenant()]

    def get_queryset(self):
        """Filtrar citas por empresa del tenant."""
        if not hasattr(self.request, "tenant"):
            return Cita.objects.none()
        
        queryset = Cita.objects.filter(empresa=self.request.tenant).select_related(
            "vehiculo", "cliente", "plan_servicio", "asesor_responsable",
            "cancelada_por"
        ).prefetch_related("detalles", "espacios_segmentos")
        
        # Filtrado segÃºn rol
        rol_nombre = self.request.user.rol.nombre if self.request.user.rol else None
        if rol_nombre == "USUARIO":
            # Los clientes solo ven citas donde son clientes
            queryset = queryset.filter(cliente=self.request.user)
        
        return queryset

    def get_serializer_class(self):
        """Usar serializer diferente segÃºn la acciÃ³n."""
        if self.action == "list":
            return CitaListadoSerializer
        elif self.action == "create":
            return CitaCreacionSerializer
        elif self.action in ["update", "partial_update"]:
            return CitaEdicionSerializer
        elif self.action == "cancelar":
            return CitaCancelacionSerializer
        # CU21 Acciones - Uso de serializers especÃ­ficos
        elif self.action == "recepcion_operativa":
            # GET /citas/recepcion-operativa/ - lista operativa
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaListadoSerializer
            return CitaRecepcionOperativaListadoSerializer
        elif self.action == "recepcion_detalle":
            # GET /citas/{id}/recepcion/ - detalle operativo
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaDetalleSerializer
            return CitaRecepcionOperativaDetalleSerializer
        elif self.action == "registrar_llegada":
            # POST /citas/{id}/registrar-llegada/ - input con RegistrarLlegadaSerializer
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import RegistrarLlegadaSerializer
            return RegistrarLlegadaSerializer
        elif self.action == "ajustar_servicios_recepcion":
            # PATCH /citas/{id}/ajustar-servicios-recepcion/ - input con AjustarServiciosRecepcionSerializer
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import AjustarServiciosRecepcionSerializer
            return AjustarServiciosRecepcionSerializer
        elif self.action == "marcar_en_proceso":
            # POST /citas/{id}/marcar-en-proceso/ - input con MarcarEnProcesoSerializer
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import MarcarEnProcesoSerializer
            return MarcarEnProcesoSerializer
        elif self.action == "marcar_vehiculo_devuelto":
            # POST /citas/{id}/marcar-vehiculo-devuelto/ - input con MarcarVehiculoDevueltoSerializer
            from modulos.vehiculos_servicios_plan_citas.serializers.taller import MarcarVehiculoDevueltoSerializer
            return MarcarVehiculoDevueltoSerializer
        else:
            # Para retrieve, destroy y otras
            return CitaDetalleSerializer

    def get_serializer_context(self):
        """Agregar contexto necesario para serializers."""
        context = super().get_serializer_context()
        context["empresa"] = self.request.tenant if hasattr(self.request, "tenant") else None
        context["usuario_autenticado"] = self.request.user
        # Pasar la instancia si estÃ¡ disponible (para validaciones en update)
        if hasattr(self, 'kwargs') and 'pk' in self.kwargs:
            try:
                context["instance"] = self.get_object()
            except:
                pass
        return context

    def destroy(self, request, *args, **kwargs):
        """
        Las citas NO se pueden eliminar. Deben cancelarse mediante la acciÃ³n 'cancelar'.
        Retorna 405 MethodNotAllowed.
        """
        return Response(
            {"error": "Las citas no se pueden eliminar. Use POST /citas/{id}/cancelar/ para cancelarla."},
            status=status.HTTP_405_METHOD_NOT_ALLOWED
        )

    def create(self, request, *args, **kwargs):
        """
        Crear una nueva cita con detalles y espacios.
        
        IMPORTANTE - NUEVA LÃ“GICA:
        - Segmentos son CALCULADOS por el backend en el serializer (fuente de verdad)
        - El estado inicial se determina segÃºn el rol del creador
        - Las fechas de inicio/fin se extraen del primer/Ãºltimo segmento
        
        Validaciones obligatorias:
        1. VehÃ­culo existe y pertenece al tenant
        2. VehÃ­culo tiene plan operativo vÃ¡lido
        3. Cliente existe y pertenece al tenant
        4. Los detalles del plan existen y pertenecen al plan del vehÃ­culo
        5. Un mismo detalle del plan no estÃ¡ en otra cita activa
        6. Espacios y segmentos son vÃ¡lidos (calculados por backend)
        7. No hay solapamiento de espacios
        """
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Extraer datos validados
            vehiculo = serializer.validated_data["vehiculo"]
            plan_servicio = serializer.validated_data["plan_servicio"]
            servicios_ids = serializer.validated_data["servicios_plan_detalle_ids"]
            canal_origen = serializer.validated_data["canal_origen"]
            cliente_id = serializer.validated_data.get("cliente_id")
            duracion_minima = serializer.validated_data.get("duracion_minima", 0)
            motivo_visita = serializer.validated_data.get("motivo_visita", "")
            observaciones = serializer.validated_data.get("observaciones_cliente", "")
            
            # NUEVO: Segmentos calculados por el backend (fuente de verdad)
            segmentos_canonicos = serializer.validated_data.get("segmentos_canonicos", [])
            fragmentado = serializer.validated_data.get("fragmentado", False)
            
            # NUEVO: Estado inicial segÃºn rol
            estado_inicial = CitasProgramacionService.construir_estado_inicial_cita(request.user)

            # Determinar cliente
            if cliente_id:
                cliente = Usuario.objects.get(id=cliente_id, empresa=self.request.tenant)
            else:
                cliente = vehiculo.propietario

            # NUEVO: Extraer fecha/hora de inicio y fin de los segmentos canÃ³nicos
            if not segmentos_canonicos:
                return Response(
                    {"error": "No se pudieron generar segmentos vÃ¡lidos para la cita."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            fecha_hora_inicio_programada = segmentos_canonicos[0]["inicio_dt"]
            fecha_hora_fin_programada = segmentos_canonicos[-1]["fin_dt"]

            # Crear cita
            cita = Cita.objects.create(
                empresa=self.request.tenant,
                vehiculo=vehiculo,
                cliente=cliente,
                plan_servicio=plan_servicio,
                estado=estado_inicial,  # NUEVO: Estado segÃºn rol
                canal_origen=canal_origen,
                fecha_hora_inicio_programada=fecha_hora_inicio_programada,  # NUEVO: Del primer segmento
                fecha_hora_fin_programada=fecha_hora_fin_programada,  # NUEVO: Del Ãºltimo segmento
                duracion_estimada_min=duracion_minima,  # NUEVO: Suma de tiempos estÃ¡ndar
                motivo_visita=motivo_visita,
                observaciones_cliente=observaciones,
                asesor_responsable=request.user if request.user.rol and request.user.rol.nombre in ["ASESOR DE SERVICIO", "ADMIN"] else None,
            )

            # Crear CitaDetalles
            servicios = PlanServicioDetalle.objects.filter(id__in=servicios_ids)
            for idx, servicio_detalle in enumerate(servicios):
                CitaDetalle.objects.create(
                    empresa=self.request.tenant,
                    cita=cita,
                    plan_detalle=servicio_detalle,
                    servicio_catalogo=servicio_detalle.servicio_catalogo,
                    estado=EstadoPlanServicioDetalle.PROGRAMADO,
                    tiempo_estandar_min=servicio_detalle.tiempo_estandar_min,
                    precio_referencial=servicio_detalle.precio_referencial,
                    orden_visual=idx,
                )
                # Cambiar estado en el plan
                servicio_detalle.estado = EstadoPlanServicioDetalle.PROGRAMADO
                servicio_detalle.save(update_fields=["estado", "updated_at"])

            # NUEVO: Crear CitaEspacioSegmentos desde segmentos canÃ³nicos
            espacio = serializer.validated_data.get("espacio")
            for orden, segmento_canonico in enumerate(segmentos_canonicos, 1):
                CitaEspacioSegmento.objects.create(
                    empresa=self.request.tenant,
                    cita=cita,
                    espacio_trabajo=espacio,
                    orden_segmento=orden,
                    tipo_segmento="TALLER",  # Default; puede personalizarse segÃºn negocio
                    inicio_programado=segmento_canonico["inicio_dt"],
                    fin_programado=segmento_canonico["fin_dt"],
                    motivo=f"Fragmento de reserva {'(fragmentado)' if fragmentado else ''}",
                )

            # CU22: presupuesto automático al crear cita.
            from decimal import Decimal
            from modulos.atencion_tecnica_ejecucion.models import (
                PresupuestoCita,
                PresupuestoDetalle,
                EstadoPresupuestoCita,
                EstadoPresupuestoDetalle,
            )

            presupuesto = PresupuestoCita.objects.create(
                empresa=self.request.tenant,
                cita=cita,
                estado=EstadoPresupuestoCita.BORRADOR,
                descuento=Decimal("0.00"),
                observaciones="Generado automáticamente al crear la cita.",
            )
            subtotal_pres = Decimal("0.00")
            for det_cita in cita.detalles.all().order_by("orden_visual", "created_at"):
                precio = det_cita.precio_referencial or Decimal("0.00")
                PresupuestoDetalle.objects.create(
                    empresa=self.request.tenant,
                    presupuesto=presupuesto,
                    servicio_catalogo=det_cita.servicio_catalogo,
                    descripcion=(det_cita.servicio_catalogo.nombre if det_cita.servicio_catalogo else "Servicio"),
                    cantidad=1,
                    tiempo_estandar_min=det_cita.tiempo_estandar_min or 0,
                    precio_unitario=precio,
                    subtotal=precio,
                    estado=EstadoPresupuestoDetalle.ACTIVO,
                )
                subtotal_pres += precio
            presupuesto.subtotal = subtotal_pres
            presupuesto.total = subtotal_pres
            presupuesto.save(update_fields=["subtotal", "total", "updated_at"])

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=self.request.tenant,
                usuario=request.user,
                accion=AccionAuditoria.CITA_CREADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Cita creada para vehÃ­culo {vehiculo.placa}. Estado: {estado_inicial}. FragmentaciÃ³n: {fragmentado}.",
                metadata={
                    "vehiculo_placa": vehiculo.placa,
                    "cliente_email": cliente.email if cliente else None,
                    "servicios_count": len(servicios_ids),
                    "segmentos_count": len(segmentos_canonicos),
                    "estado_inicial": estado_inicial,
                    "fragmentado": fragmentado,
                },
            )

        # Retornar cita creada (usar CitaDetalleSerializer para respuesta completa)
        detail_serializer = CitaDetalleSerializer(
            cita, 
            context=self.get_serializer_context()
        )
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """
        Editar una cita (solo si estÃ¡ PROGRAMADA).
        Permite cambiar fecha, hora, observaciones, detalles y espacios.
        """
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        # Verificar permisos
        self.check_object_permissions(request, instance)

        # Validar que la cita sea editable
        if instance.estado != EstadoCita.PROGRAMADA:
            return Response(
                {"error": f"No se puede editar una cita en estado {instance.estado}. "
                          f"Solo citas PROGRAMADAS son editables."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Cambios anteriores para auditorÃ­a
            cambios_dict = construir_cambios(instance, serializer.validated_data)

            # Actualizar campos de cita desde validated_data
            if "fecha_hora_inicio_programada" in serializer.validated_data:
                instance.fecha_hora_inicio_programada = serializer.validated_data[
                    "fecha_hora_inicio_programada"
                ]
            if "fecha_hora_fin_programada" in serializer.validated_data:
                instance.fecha_hora_fin_programada = serializer.validated_data[
                    "fecha_hora_fin_programada"
                ]
            if "motivo_visita" in serializer.validated_data:
                instance.motivo_visita = serializer.validated_data["motivo_visita"]
            if "observaciones_cliente" in serializer.validated_data:
                instance.observaciones_cliente = serializer.validated_data["observaciones_cliente"]

            instance.updated_at = timezone.now()
            instance.save()

            # Actualizar espacios si viene en validated_data
            if "segmentos_espacio" in serializer.validated_data:
                segmentos_data = serializer.validated_data["segmentos_espacio"]
                # Eliminar segmentos anteriores
                instance.espacios_segmentos.all().delete()
                # Crear nuevos segmentos
                for orden, segmento_data in enumerate(segmentos_data, 1):
                    espacio = EspacioTrabajo.objects.get(
                        id=segmento_data["espacio_trabajo_id"],
                        empresa=self.request.tenant
                    )
                    CitaEspacioSegmento.objects.create(
                        empresa=self.request.tenant,
                        cita=instance,
                        espacio_trabajo=espacio,
                        orden_segmento=orden,
                        tipo_segmento=segmento_data["tipo_segmento"],
                        inicio_programado=segmento_data["inicio_programado"],
                        fin_programado=segmento_data["fin_programado"],
                    )

            # Actualizar servicios si viene en validated_data
            if "servicios_plan_detalle_ids" in serializer.validated_data:
                nuevos_servicios_ids = serializer.validated_data["servicios_plan_detalle_ids"]
                
                # Validar que ninguno de los nuevos servicios estÃ¡ en otra cita activa
                citas_activas_con_servicios = CitaDetalle.objects.filter(
                    plan_detalle_id__in=nuevos_servicios_ids,
                    cita__empresa=self.request.tenant,
                    cita__estado__in=[EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
                ).exclude(cita=instance).exists()
                
                if citas_activas_con_servicios:
                    raise serializers.ValidationError(
                        {"servicios_plan_detalle_ids": "Algunos servicios ya estÃ¡n asignados a otras citas activas."}
                    )
                
                # Eliminar detalles anteriores y liberar servicios
                for cita_detalle in instance.detalles.all():
                    if cita_detalle.plan_detalle:
                        cita_detalle.plan_detalle.estado = EstadoPlanServicioDetalle.PENDIENTE
                        cita_detalle.plan_detalle.save(update_fields=["estado", "updated_at"])
                    cita_detalle.delete()
                
                # Crear nuevos detalles
                nuevos_servicios = PlanServicioDetalle.objects.filter(
                    id__in=nuevos_servicios_ids,
                    plan_servicio=instance.plan_servicio,
                    empresa=self.request.tenant
                )
                
                for idx, servicio_detalle in enumerate(nuevos_servicios):
                    CitaDetalle.objects.create(
                        empresa=self.request.tenant,
                        cita=instance,
                        plan_detalle=servicio_detalle,
                        servicio_catalogo=servicio_detalle.servicio_catalogo,
                        estado=EstadoPlanServicioDetalle.PROGRAMADO,
                        tiempo_estandar_min=servicio_detalle.tiempo_estandar_min,
                        precio_referencial=servicio_detalle.precio_referencial,
                        orden_visual=idx,
                    )
                    # Marcar como programado en el plan
                    servicio_detalle.estado = EstadoPlanServicioDetalle.PROGRAMADO
                    servicio_detalle.save(update_fields=["estado", "updated_at"])

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=self.request.tenant,
                usuario=request.user,
                accion=AccionAuditoria.CITA_ACTUALIZADA,
                entidad_tipo="Cita",
                entidad_id=str(instance.id),
                descripcion=f"Cita actualizada",
                metadata=cambios_dict,
            )

        # Responder con CitaDetalleSerializer (full detail, no solo edit fields)
        detail_serializer = CitaDetalleSerializer(
            instance, 
            context=self.get_serializer_context()
        )
        return Response(detail_serializer.data)

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticatedTenant, PuedeGestionarCitas])
    def cancelar(self, request, pk=None, **kwargs):
        """
        Cancelar una cita.
        
        Validaciones:
        1. Solo se pueden cancelar citas en estado PROGRAMADA o EN_ESPERA_INGRESO
        2. No se pueden cancelar citas EN_PROCESO, FINALIZADA, etc.
        
        LÃ³gica:
        1. Cambiar estado de la cita a CANCELADA
        2. Liberar los detalles del plan (volver a PENDIENTE)
        3. Guardar motivo de cancelaciÃ³n
        4. Guardar quiÃ©n cancelÃ³
        5. Registrar en auditorÃ­a
        """
        cita = self.get_object()

        # Verificar permisos
        self.check_object_permissions(request, cita)

        # Validar que no estÃ© ya cancelada
        if cita.estado == EstadoCita.CANCELADA:
            return Response(
                {"error": "La cita ya estÃ¡ cancelada."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # ** VALIDAR que solo se cancelen citas PROGRAMADA o EN_ESPERA_INGRESO **
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            return Response(
                {"error": f"No se puede cancelar una cita en estado {cita.estado}. "
                          f"Solo citas PROGRAMADAS o EN_ESPERA_INGRESO pueden cancelarse."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Obtener motivo desde request data
        motivo = request.data.get("motivo_cancelacion", "")

        with transaction.atomic():
            # Actualizar cita
            cita.estado = EstadoCita.CANCELADA
            cita.cancelada_por = request.user
            cita.motivo_cancelacion = motivo
            cita.save()

            # Liberar detalles del plan
            for cita_detalle in cita.detalles.all():
                if cita_detalle.plan_detalle:
                    cita_detalle.plan_detalle.estado = EstadoPlanServicioDetalle.PENDIENTE
                    cita_detalle.plan_detalle.save(update_fields=["estado", "updated_at"])

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=self.request.tenant,
                usuario=request.user,
                accion=AccionAuditoria.CITA_ELIMINADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion=f"Cita cancelada: {motivo}",
                metadata={"motivo": motivo},
            )

        return Response(
            {"mensaje": "Cita cancelada exitosamente.", "estado": cita.estado},
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=["post"], permission_classes=[IsAuthenticatedTenant, PuedeGestionarCitas])
    def reprogramar(self, request, pk=None, **kwargs):
        """
        Reprogramar una cita.
        
        LÃ³gica:
        1. Marcar cita original como REPROGRAMADA (estado)
        2. Crear nueva cita con nuevas fechas/espacios
        3. Copiar detalles de la cita original
        4. Incrementar contador de reprogramaciones en la nueva cita
        5. Mantener trazabilidad
        
        Payload esperado:
        {
            "fecha_hora_inicio_programada": "2026-03-25T10:00:00Z",
            "fecha_hora_fin_programada": "2026-03-25T12:00:00Z",
            "segmentos_espacio": [{...}],  # Requerido o auto-copia desde original
            "motivo_reprogramacion": "cliente lo requested"
        }
        """
        cita_original = self.get_object()

        # Validar que la cita sea reprogramable
        if cita_original.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            return Response(
                {"error": f"No se puede reprogramar una cita en estado {cita_original.estado}."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            # Obtener datos de la nueva cita
            fecha_inicio = serializer.validated_data["fecha_hora_inicio_programada"]
            fecha_fin = serializer.validated_data["fecha_hora_fin_programada"]
            
            # ** NUEVO: Si no vienen segmentos, copiar desde original **
            segmentos_data = serializer.validated_data.get("segmentos_espacio", None)
            if not segmentos_data:
                # Auto-copiar de la cita original
                segmentos_originales = cita_original.espacios_segmentos.all()
                if not segmentos_originales.exists():
                    raise serializers.ValidationError(
                        {"segmentos_espacio": "Debe proporcionar segmentos de espacio o la cita original debe tener segmentos para copiar."}
                    )
                # Convertir a formato esperado por validaciÃ³n
                segmentos_data = [
                    {
                        "espacio_trabajo_id": seg.espacio_trabajo.id,
                        "tipo_segmento": seg.tipo_segmento,
                        "inicio_programado": seg.inicio_programado,
                        "fin_programado": seg.fin_programado,
                    }
                    for seg in segmentos_originales
                ]
            
            motivo = serializer.validated_data.get("motivo_reprogramacion", "")

            # ** VALIDACIÃ“N: Verificar conflictos de espacios antes de crear nueva cita **
            validar_conflictos_espacios_en_bd(segmentos_data, self.request.tenant.id, excluir_cita_id=None)

            # Crear nueva cita basada en la original
            nueva_cita = Cita.objects.create(
                empresa=self.request.tenant,
                vehiculo=cita_original.vehiculo,
                cliente=cita_original.cliente,
                plan_servicio=cita_original.plan_servicio,
                estado=EstadoCita.PROGRAMADA,
                canal_origen=cita_original.canal_origen,
                fecha_hora_inicio_programada=fecha_inicio,
                fecha_hora_fin_programada=fecha_fin,
                duracion_estimada_min=(fecha_fin - fecha_inicio).total_seconds() // 60,
                motivo_visita=cita_original.motivo_visita,
                observaciones_cliente=cita_original.observaciones_cliente,
                asesor_responsable=cita_original.asesor_responsable,
                reprogramaciones_count=cita_original.reprogramaciones_count + 1,
            )

            # Copiar detalles de la cita original a la nueva
            for cita_detalle_original in cita_original.detalles.all():
                CitaDetalle.objects.create(
                    empresa=self.request.tenant,
                    cita=nueva_cita,
                    plan_detalle=cita_detalle_original.plan_detalle,
                    servicio_catalogo=cita_detalle_original.servicio_catalogo,
                    estado=EstadoPlanServicioDetalle.PROGRAMADO,
                    tiempo_estandar_min=cita_detalle_original.tiempo_estandar_min,
                    precio_referencial=cita_detalle_original.precio_referencial,
                    orden_visual=cita_detalle_original.orden_visual,
                )

            # Crear nuevos espacios
            for orden, segmento_data in enumerate(segmentos_data, 1):
                espacio = EspacioTrabajo.objects.get(
                    id=segmento_data["espacio_trabajo_id"],
                    empresa=self.request.tenant
                )
                CitaEspacioSegmento.objects.create(
                    empresa=self.request.tenant,
                    cita=nueva_cita,
                    espacio_trabajo=espacio,
                    orden_segmento=orden,
                    tipo_segmento=segmento_data["tipo_segmento"],
                    inicio_programado=segmento_data["inicio_programado"],
                    fin_programado=segmento_data["fin_programado"],
                )

            # ** NUEVO: Marcar cita original como REPROGRAMADA (no solo guardar fecha/motivo) **
            cita_original.estado = EstadoCita.REPROGRAMADA
            cita_original.ultima_reprogramacion_at = timezone.now()
            cita_original.motivo_ultima_reprogramacion = motivo
            cita_original.save()

            # Registrar auditorÃ­a
            registrar_evento_on_commit(
                empresa=self.request.tenant,
                usuario=request.user,
                accion=AccionAuditoria.CITA_CREADA,
                entidad_tipo="Cita",
                entidad_id=str(nueva_cita.id),
                descripcion=f"Cita reprogramada desde {cita_original.id}",
                metadata={
                    "cita_original_id": str(cita_original.id),
                    "motivo": motivo,
                    "fechas_anteriores": {
                        "inicio": str(cita_original.fecha_hora_inicio_programada),
                        "fin": str(cita_original.fecha_hora_fin_programada),
                    },
                    "fechas_nuevas": {
                        "inicio": str(fecha_inicio),
                        "fin": str(fecha_fin),
                    },
                },
            )

        serializer_respuesta = self.get_serializer(nueva_cita)
        return Response(serializer_respuesta.data, status=status.HTTP_201_CREATED)

    @action(
        detail=True,
        methods=["post"],
        url_path="marcar-no-show",
        permission_classes=[IsAuthenticatedTenant, PuedeGestionarCitas],
    )
    def marcar_no_show(self, request, pk=None, **kwargs):
        """
        POST /api/{slug}/citas/{id}/marcar-no-show/
        """
        from datetime import timedelta

        cita = self.get_object()
        self.check_object_permissions(request, cita)

        if cita.estado == EstadoCita.NO_SHOW:
            return Response(
                {
                    "mensaje": "La cita ya está marcada como no-show.",
                    "estado": cita.estado,
                    "no_show_marcado_at": cita.no_show_marcado_at.isoformat() if cita.no_show_marcado_at else None,
                },
                status=status.HTTP_200_OK,
            )

        estados_permitidos = [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]
        if cita.estado not in estados_permitidos:
            return Response(
                {
                    "error": (
                        f"No se puede marcar no-show para una cita en estado {cita.estado}. "
                        "Solo PROGRAMADA o EN_ESPERA_INGRESO."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        ahora = timezone.now()
        limite_tolerancia = cita.fecha_hora_inicio_programada + timedelta(minutes=self.NO_SHOW_TOLERANCIA_MIN)
        if ahora < limite_tolerancia:
            return Response(
                {
                    "error": (
                        "La cita aún está dentro del tiempo de tolerancia para no-show. "
                        f"Tolerancia: {self.NO_SHOW_TOLERANCIA_MIN} minutos."
                    ),
                    "puede_marcar_desde": limite_tolerancia.isoformat(),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        observacion = request.data.get("observacion", "")

        with transaction.atomic():
            cita.estado = EstadoCita.NO_SHOW
            cita.no_show_marcado_at = ahora
            if observacion:
                cita.motivo_cancelacion = observacion
            cita.save(update_fields=["estado", "no_show_marcado_at", "motivo_cancelacion", "updated_at"])

            for cita_detalle in cita.detalles.all():
                if cita_detalle.plan_detalle:
                    cita_detalle.plan_detalle.estado = EstadoPlanServicioDetalle.PENDIENTE
                    cita_detalle.plan_detalle.save(update_fields=["estado", "updated_at"])

            registrar_evento_on_commit(
                empresa=self.request.tenant,
                usuario=request.user,
                accion=AccionAuditoria.CITA_ACTUALIZADA,
                entidad_tipo="Cita",
                entidad_id=str(cita.id),
                descripcion="Cita marcada como no-show",
                metadata={
                    "estado_nuevo": EstadoCita.NO_SHOW,
                    "no_show_marcado_at": ahora.isoformat(),
                    "observacion": observacion,
                },
            )

        return Response(
            {
                "mensaje": "Cita marcada como no-show.",
                "estado": cita.estado,
                "no_show_marcado_at": cita.no_show_marcado_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="preview-intencion")
    def preview_intencion(self, request, **kwargs):
        """
        Preview/ValidaciÃ³n tentativa de una INTENCIÃ“N de cita.
        
        NO persiste nada. Solo calcula quÃ© pasarÃ­a si se crea la cita con esos parÃ¡metros.
        
        Payload esperado (POST /api/{slug}/citas/preview-intencion/):
        {
            "vehiculo_id": "uuid-del-vehiculo",
            "servicios_ids": ["uuid-servicio1", "uuid-servicio2"],
            "fecha_hora_inicio": "2026-03-25T10:00:00Z",
            "espacio_trabajo_id": "uuid-espacio" (opcional)
        }
        
        Response:
        {
            "fecha_hora_inicio_respuesta": "2026-03-25T10:00:00Z",
            "fecha_hora_fin_estimada": "2026-03-25T12:30:00Z",
            "es_valida": true,
            "duracion_total_min": 150,
            "fragmentado": false,
            "segmentos_preview": [
                {
                    "numero": 1,
                    "espacio": "BahÃ­a 1",
                    "inicio": "2026-03-25T10:00:00Z",
                    "fin": "2026-03-25T12:30:00Z",
                    "duracion_min": 150
                }
            ],
            "mensajes": ["âœ“ La cita se puede programar correctamente."]
        }
        """
        serializer = CitaPreviewIntencionSerializer(
            data=request.data,
            context={
                "empresa": request.tenant,
                "usuario_autenticado": request.user,
            }
        )
        
        if serializer.is_valid():
            # Invocar create() que retorna el dict calculado (no persistido)
            resultado = serializer.create(serializer.validated_data)
            return Response(resultado, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="validar-disponibilidad-espacio")
    def validar_disponibilidad_espacio(self, request, **kwargs):
        """
        POST /api/{slug}/citas/validar-disponibilidad-espacio/

        Valida si un espacio especÃ­fico puede alojar una cita desde una fecha/hora dada.
        Si NO puede, recomienda el PRIMER horario realmente disponible que:
        - respete horarios laborales del espacio
        - respete ocupaciÃ³n existente
        - tenga duraciÃ³n suficiente
        - agote bloques del mismo dÃ­a antes de pasar al siguiente
        """
        empresa = self.request.tenant if hasattr(self.request, "tenant") else None

        if not empresa:
            return Response(
                {"detail": "Tenant no encontrado"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            espacio_id = request.data.get("espacio_trabajo_id")
            fecha_hora_inicio_str = request.data.get("fecha_hora_inicio")
            duracion_requerida_min = request.data.get("duracion_requerida_min", 90)

            if not all([espacio_id, fecha_hora_inicio_str]):
                return Response(
                    {
                        "detail": (
                            "Faltan parÃ¡metros requeridos: "
                            "espacio_trabajo_id, fecha_hora_inicio"
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                duracion_requerida_min = int(duracion_requerida_min)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "duracion_requerida_min debe ser un entero vÃ¡lido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if duracion_requerida_min <= 0:
                return Response(
                    {"detail": "duracion_requerida_min debe ser mayor que 0."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            espacio = EspacioTrabajo.objects.get(id=espacio_id, empresa=empresa)

            fecha_hora_inicio = self._parse_datetime(fecha_hora_inicio_str)

            # 1) ValidaciÃ³n temporal bÃ¡sica (no pasado / hoy no vencido)
            valido_temp, error_temp = CitasProgramacionService.validar_inicio_no_pasado(
                fecha_hora_inicio, empresa
            )
            if not valido_temp:
                return Response(
                    {
                        "disponible": False,
                        "fecha_hora_solicitada": fecha_hora_inicio.isoformat(),
                        "razon": "Inicio invÃ¡lido",
                        "proximo_horario_disponible": None,
                        "espacio_nombre": espacio.nombre,
                        "mensaje": error_temp,
                    },
                    status=status.HTTP_200_OK,
                )

            # 2) Validar si la cita puede comenzar EXACTAMENTE en la hora solicitada
            resultado = CitasProgramacionService.construir_reserva_desde_inicio_exacto(
                espacio_id=str(espacio.id),
                fecha_hora_inicio=fecha_hora_inicio,
                duracion_requerida_min=duracion_requerida_min,
                empresa=empresa,
                horizonte_dias=30,
            )

            if resultado.valido:
                fecha_hora_fin_estimada = resultado.segmentos[-1]["fin_dt"] if resultado.segmentos else None

                return Response(
                    {
                        "disponible": True,
                        "fecha_hora_inicio": fecha_hora_inicio.isoformat(),
                        "fecha_hora_fin_estimada": (
                            fecha_hora_fin_estimada.isoformat()
                            if fecha_hora_fin_estimada else None
                        ),
                        "espacio_nombre": espacio.nombre,
                        "duracion_requerida_min": duracion_requerida_min,
                        "fragmentado": resultado.fragmentado,
                        "segmentos_sugeridos": self._serializar_segmentos(resultado.segmentos),
                        "mensaje": "âœ“ Espacio disponible en el horario solicitado",
                    },
                    status=status.HTTP_200_OK,
                )

            # 3) Si no cabe exactamente ahÃ­, buscar el PRIMER inicio realmente vÃ¡lido
            sugerencia = CitasProgramacionService.encontrar_primer_inicio_disponible(
                espacio_id=str(espacio.id),
                fecha_hora_inicio=fecha_hora_inicio,
                duracion_requerida_min=duracion_requerida_min,
                empresa=empresa,
                horizonte_dias=30,
            )

            if sugerencia:
                return Response(
                    {
                        "disponible": False,
                        "fecha_hora_solicitada": fecha_hora_inicio.isoformat(),
                        "razon": "Espacio no disponible en el horario solicitado",
                        "proximo_horario_disponible": sugerencia["inicio_dt"].isoformat(),
                        "fecha_hora_fin_estimada": sugerencia["fin_dt"].isoformat(),
                        "espacio_nombre": espacio.nombre,
                        "duracion_requerida_min": duracion_requerida_min,
                        "fragmentado": sugerencia["fragmentado"],
                        "segmentos_sugeridos": self._serializar_segmentos(sugerencia["segmentos"]),
                        "mensaje": (
                            f"El espacio no estÃ¡ disponible en el horario solicitado. "
                            f"PrÃ³ximo horario disponible real: "
                            f"{sugerencia['inicio_dt'].strftime('%H:%M %d/%m/%Y')}"
                        ),
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "disponible": False,
                    "fecha_hora_solicitada": fecha_hora_inicio.isoformat(),
                    "razon": "Sin disponibilidad en los prÃ³ximos 30 dÃ­as",
                    "proximo_horario_disponible": None,
                    "espacio_nombre": espacio.nombre,
                    "duracion_requerida_min": duracion_requerida_min,
                    "mensaje": (
                        "No hay disponibilidad real en este espacio para "
                        "los prÃ³ximos 30 dÃ­as."
                    ),
                },
                status=status.HTTP_200_OK,
            )

        except EspacioTrabajo.DoesNotExist:
            return Response(
                {"detail": "Espacio de trabajo no encontrado"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Error validando disponibilidad de espacio")
            return Response(
                {"detail": f"Error al validar disponibilidad: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["get"], url_path="bloques-disponibles")
    def bloques_disponibles(self, request, **kwargs):
        """
        GET /api/{slug}/citas/bloques-disponibles/

        Query params:
        - espacio_trabajo_id (UUID, requerido)
        - fecha (YYYY-MM-DD, requerido)
        - duracion_min (int, requerido)
        - horizonte_dias (int, opcional, default 30)
        - max_resultados (int, opcional, default 80)
        """
        from datetime import datetime, timedelta
        from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService

        empresa = self.request.tenant if hasattr(self.request, "tenant") else None
        if not empresa:
            return Response({"detail": "Tenant no encontrado"}, status=status.HTTP_400_BAD_REQUEST)

        espacio_id = request.query_params.get("espacio_trabajo_id")
        fecha_str = request.query_params.get("fecha")
        duracion_min_str = request.query_params.get("duracion_min")
        horizonte_str = request.query_params.get("horizonte_dias", "30")
        max_resultados_str = request.query_params.get("max_resultados", "80")

        if not espacio_id or not fecha_str or not duracion_min_str:
            return Response(
                {"detail": "Parámetros requeridos: espacio_trabajo_id, fecha, duracion_min"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            duracion_min = int(duracion_min_str)
            horizonte_dias = int(horizonte_str)
            max_resultados = int(max_resultados_str)
        except ValueError:
            return Response(
                {"detail": "duracion_min, horizonte_dias y max_resultados deben ser enteros"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if duracion_min <= 0:
            return Response({"detail": "duracion_min debe ser mayor que 0"}, status=status.HTTP_400_BAD_REQUEST)
        if duracion_min % 30 != 0:
            return Response({"detail": "duracion_min debe ser múltiplo de 30"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            espacio = EspacioTrabajo.objects.get(id=espacio_id, empresa=empresa)
        except EspacioTrabajo.DoesNotExist:
            return Response({"detail": "Espacio de trabajo no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        try:
            fecha_base = datetime.strptime(fecha_str, "%Y-%m-%d")
        except ValueError:
            return Response({"detail": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=status.HTTP_400_BAD_REQUEST)

        tz_operativa = CitasProgramacionService.obtener_timezone_operativa(empresa)
        fecha_base_op = tz_operativa.localize(datetime.combine(fecha_base.date(), datetime.min.time()))

        resultados = []
        for offset in range(horizonte_dias):
            if len(resultados) >= max_resultados:
                break

            fecha_actual = fecha_base_op + timedelta(days=offset)
            ventanas = CitasProgramacionService.obtener_ventanas_operativas_dia(
                espacio_id=str(espacio.id),
                fecha=fecha_actual,
                empresa=empresa,
            )
            if not ventanas:
                continue

            ocupacion = CitasProgramacionService.obtener_ocupacion_espacio_dia(
                espacio_id=str(espacio.id),
                fecha=fecha_actual,
                empresa=empresa,
            )
            ventanas_libres = CitasProgramacionService.restar_ocupacion_ventanas(ventanas, ocupacion)

            inicio_minimo = None
            if offset == 0:
                inicio_minimo = 0

            candidatos = CitasProgramacionService._bloques_inicio_desde_ventanas(
                ventanas_libres,
                inicio_minimo=inicio_minimo,
            )

            for minuto in candidatos:
                dt_op = tz_operativa.localize(
                    datetime.combine(
                        fecha_actual.date(),
                        datetime.min.time().replace(hour=minuto // 60, minute=minuto % 60),
                    )
                )
                dt_utc = dt_op.astimezone(timezone.utc)

                valido_temp, _ = CitasProgramacionService.validar_inicio_no_pasado(dt_utc, empresa)
                if not valido_temp:
                    continue

                res = CitasProgramacionService.construir_reserva_desde_inicio_exacto(
                    espacio_id=str(espacio.id),
                    fecha_hora_inicio=dt_utc,
                    duracion_requerida_min=duracion_min,
                    empresa=empresa,
                    horizonte_dias=horizonte_dias,
                )
                if not res.valido:
                    continue

                resultados.append(
                    {
                        "inicio": dt_utc.isoformat(),
                        "fecha": dt_op.strftime("%Y-%m-%d"),
                        "hora": dt_op.strftime("%H:%M"),
                    }
                )
                if len(resultados) >= max_resultados:
                    break

        return Response(
            {
                "espacio_id": str(espacio.id),
                "espacio_nombre": espacio.nombre,
                "duracion_min": duracion_min,
                "fecha_base": fecha_base_op.strftime("%Y-%m-%d"),
                "horizonte_dias": horizonte_dias,
                "bloques_disponibles": resultados,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path="agenda")
    def agenda(self, request, **kwargs):
        """
        GET /api/{slug}/citas/agenda/

        Query params:
        - vista: dia|semana|lista (default: dia)
        - fecha: YYYY-MM-DD (default: hoy)
        - estado, cliente_id, vehiculo_id, espacio_id, asesor_id, search (opcionales)
        """
        from datetime import datetime, timedelta

        vista = request.query_params.get("vista", "dia").lower()
        if vista not in ["dia", "semana", "lista"]:
            return Response({"detail": "vista inválida. Use dia, semana o lista."}, status=status.HTTP_400_BAD_REQUEST)

        fecha_str = request.query_params.get("fecha")
        if fecha_str:
            try:
                fecha_base = datetime.strptime(fecha_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"detail": "fecha inválida. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            fecha_base = timezone.now().date()

        if vista == "semana":
            inicio_rango = fecha_base - timedelta(days=fecha_base.weekday())
            fin_rango = inicio_rango + timedelta(days=6)
        else:
            inicio_rango = fecha_base
            fin_rango = fecha_base

        queryset = self.get_queryset().filter(
            fecha_hora_inicio_programada__date__gte=inicio_rango,
            fecha_hora_inicio_programada__date__lte=fin_rango,
        ).select_related(
            "vehiculo", "cliente", "asesor_responsable"
        ).prefetch_related(
            "detalles__servicio_catalogo",
            "espacios_segmentos__espacio_trabajo",
        )

        estado = request.query_params.get("estado")
        cliente_id = request.query_params.get("cliente_id")
        vehiculo_id = request.query_params.get("vehiculo_id")
        espacio_id = request.query_params.get("espacio_id")
        asesor_id = request.query_params.get("asesor_id")
        search = request.query_params.get("search")

        if estado:
            queryset = queryset.filter(estado=estado)
        if cliente_id:
            queryset = queryset.filter(cliente_id=cliente_id)
        if vehiculo_id:
            queryset = queryset.filter(vehiculo_id=vehiculo_id)
        if asesor_id:
            queryset = queryset.filter(asesor_responsable_id=asesor_id)
        if espacio_id:
            queryset = queryset.filter(espacios_segmentos__espacio_trabajo_id=espacio_id).distinct()
        if search:
            queryset = queryset.filter(
                Q(vehiculo__placa__icontains=search)
                | Q(cliente__nombres__icontains=search)
                | Q(cliente__email__icontains=search)
            )

        citas = queryset.order_by("fecha_hora_inicio_programada")
        citas_data = [self._serializar_cita_agenda(c) for c in citas]
        capacidad = self._construir_capacidad_agenda(
            empresa=self.request.tenant,
            fecha_inicio=inicio_rango,
            fecha_fin=fin_rango,
            espacio_id=espacio_id,
        )

        agrupado_por_fecha = {}
        for cita in citas_data:
            fecha_key = cita["inicio"][:10]
            agrupado_por_fecha.setdefault(fecha_key, []).append(cita)

        return Response(
            {
                "vista": vista,
                "fecha_base": str(fecha_base),
                "rango": {"inicio": str(inicio_rango), "fin": str(fin_rango)},
                "filtros": {
                    "estado": estado,
                    "cliente_id": cliente_id,
                    "vehiculo_id": vehiculo_id,
                    "espacio_id": espacio_id,
                    "asesor_id": asesor_id,
                    "search": search,
                },
                "resumen": {
                    "total_citas": len(citas_data),
                    "sin_resultados": len(citas_data) == 0,
                },
                "capacidad_espacios": capacidad,
                "citas": citas_data,
                "citas_por_fecha": agrupado_por_fecha,
            },
            status=status.HTTP_200_OK,
        )

    # ============================================================================
    # ACCIONES DE CU21 - RECEPCIÃ“N MÃNIMA DE VEHÃCULOS
    # ============================================================================

    @action(
        detail=False, 
        methods=["get"], 
        url_path="recepcion-operativa"
    )
    def recepcion_operativa(self, request, **kwargs):
        """
        GET /api/{slug}/citas/recepcion-operativa/
        
        Lista citas para la vista operativa de recepciÃ³n (CU21).
        
        Query parameters:
        - fecha: YYYY-MM-DD (default: hoy)
        - bandeja: pendientes|espera_ingreso|en_proceso|por_entregar|entregadas (optional)
        - placa: placa del vehÃ­culo (optional)
        - cliente: nombre del cliente (optional)
        - asesor_id: UUID del asesor responsable (optional)
        
        Bandeja semÃ¡ntica:
        - pendientes: PROGRAMADA sin llegada_real_at
        - espera_ingreso: EN_ESPERA_INGRESO
        - en_proceso: EN_PROCESO
        - por_entregar: FINALIZADA sin vehiculo_devuelto_at
        - entregadas: con vehiculo_devuelto_at
        """
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaListadoSerializer
        from datetime import date
        
        empresa = self.request.tenant
        usuario = request.user
        
        # ParÃ¡metros
        fecha_str = request.query_params.get("fecha", None)
        bandeja = request.query_params.get("bandeja", None)
        placa = request.query_params.get("placa", None)
        cliente_nombre = request.query_params.get("cliente", None)
        asesor_id = request.query_params.get("asesor_id", None)
        
        # Filtro base: citas del tenant
        queryset = Cita.objects.filter(empresa=empresa).select_related(
            "vehiculo", "cliente", "asesor_responsable"
        ).prefetch_related("detalles")
        
        # Filtro por fecha (dÃ­a)
        if fecha_str:
            try:
                fecha_target = date.fromisoformat(fecha_str)
                queryset = queryset.filter(
                    fecha_hora_inicio_programada__date=fecha_target
                )
            except ValueError:
                return Response(
                    {"error": "Formato de fecha invÃ¡lido. Use YYYY-MM-DD"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            # Default: hoy
            hoy = date.today()
            queryset = queryset.filter(
                fecha_hora_inicio_programada__date=hoy
            )
        
        # Filtro por bandeja operativa
        if bandeja == "pendientes":
            queryset = queryset.filter(
                estado=EstadoCita.PROGRAMADA,
                llegada_real_at__isnull=True
            )
        elif bandeja == "espera_ingreso":
            queryset = queryset.filter(estado=EstadoCita.EN_ESPERA_INGRESO)
        elif bandeja == "en_proceso":
            queryset = queryset.filter(estado=EstadoCita.EN_PROCESO)
        elif bandeja == "por_entregar":
            queryset = queryset.filter(
                finalizada_at__isnull=False,
                vehiculo_devuelto_at__isnull=True
            )
        elif bandeja == "entregadas":
            queryset = queryset.filter(vehiculo_devuelto_at__isnull=False)
        
        # Filtros adicionales
        if placa:
            queryset = queryset.filter(vehiculo__placa__icontains=placa)
        if cliente_nombre:
            queryset = queryset.filter(cliente__nombres__icontains=cliente_nombre)
        if asesor_id:
            queryset = queryset.filter(asesor_responsable_id=asesor_id)
        
        # Validar permisos segÃºn rol
        rol_nombre = usuario.rol.nombre if usuario.rol else None
        if rol_nombre == "USUARIO":
            queryset = queryset.filter(cliente=usuario)
        elif rol_nombre not in ["ADMIN", "ASESOR DE SERVICIO"]:
            # Otros roles no pueden acceder a esta vista
            queryset = queryset.none()
        
        # Ordenar por fecha de inicio
        queryset = queryset.order_by("fecha_hora_inicio_programada")
        
        # Serializar
        serializer = CitaRecepcionOperativaListadoSerializer(
            queryset, 
            many=True, 
            context={"request": request}
        )
        
        # Construir respuesta con contadores
        counters = {
            "pendientes": Cita.objects.filter(
                empresa=empresa, 
                estado=EstadoCita.PROGRAMADA, 
                llegada_real_at__isnull=True
            ).count(),
            "espera_ingreso": Cita.objects.filter(
                empresa=empresa,
                estado=EstadoCita.EN_ESPERA_INGRESO
            ).count(),
            "en_proceso": Cita.objects.filter(
                empresa=empresa,
                estado=EstadoCita.EN_PROCESO
            ).count(),
            "por_entregar": Cita.objects.filter(
                empresa=empresa,
                finalizada_at__isnull=False,
                vehiculo_devuelto_at__isnull=True
            ).count(),
            "entregadas": Cita.objects.filter(
                empresa=empresa,
                vehiculo_devuelto_at__isnull=False
            ).count(),
        }
        
        return Response({
            "fecha": fecha_str or str(date.today()),
            "bandeja": bandeja or "todas",
            "counters": counters,
            "results": serializer.data
        }, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path="recepcion"
    )
    def recepcion_detalle(self, request, pk=None, **kwargs):
        """
        GET /api/{slug}/citas/{id}/recepcion/
        
        Detalle operativo de una cita para CU21 (recepciÃ³n mÃ­nima).
        
        Retorna:
        - Datos base de cita
        - Servicios actuales (CitaDetalles)
        - Segmentos de espacio (CitaEspacioSegmentos)
        - Timestamps operativos (llegada_real_at, finalizada_at, vehiculo_devuelto_at)
        - Flags de acciones permitidas
        """
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaDetalleSerializer
        
        cita = self.get_object()
        self.check_object_permissions(request, cita)
        
        serializer = CitaRecepcionOperativaDetalleSerializer(
            cita,
            context={"request": request}
        )
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="registrar-llegada"
    )
    def registrar_llegada(self, request, pk=None, **kwargs):
        """
        POST /api/{slug}/citas/{id}/registrar-llegada/
        
        Registrar la llegada real del vehÃ­culo a la cita.
        
        Payload (opcional):
        {
            "llegada_real_at": "2026-03-25T10:15:00Z"  (opcional, default: timezone.now())
        }
        
        Validaciones:
        - Solo ADMIN o ASESOR DE SERVICIO
        - Cita debe estar PROGRAMADA o EN_ESPERA_INGRESO
        
        LÃ³gica:
        - Si PROGRAMADA: cambiar a EN_ESPERA_INGRESO
        - Si EN_ESPERA_INGRESO: mantener estado
        - Guardar llegada_real_at
        """
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaDetalleSerializer
        
        cita = self.get_object()
        self.check_object_permissions(request, cita)
        
        # Extraer parÃ¡metro opcional
        llegada_real_at = request.data.get("llegada_real_at", None)
        if llegada_real_at:
            try:
                from datetime import datetime
                llegada_real_at = datetime.fromisoformat(
                    str(llegada_real_at).replace("Z", "+00:00")
                )
                if timezone.is_naive(llegada_real_at):
                    llegada_real_at = timezone.make_aware(llegada_real_at)
            except (ValueError, TypeError):
                return Response(
                    {"error": "Formato de fecha invÃ¡lido para llegada_real_at"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            cita_actualizada = CitasRecepcionService.registrar_llegada(
                cita=cita,
                usuario=request.user,
                empresa=self.request.tenant,
                llegada_real_at=llegada_real_at
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CitaRecepcionOperativaDetalleSerializer(
            cita_actualizada,
            context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["patch"],
        url_path="ajustar-servicios-recepcion"
    )
    def ajustar_servicios_recepcion(self, request, pk=None, **kwargs):
        """
        PATCH /api/{slug}/citas/{id}/ajustar-servicios-recepcion/
        
        Ajustar los servicios de una cita antes de iniciar trabajo.
        
        Payload:
        {
            "servicios_plan_detalle_ids": ["uuid1", "uuid2", "uuid3"],
            "motivo_visita": "revisiÃ³n de motores",
            "observaciones_cliente": "lo necesito rÃ¡pido"
        }
        
        Validaciones:
        - Solo ADMIN o ASESOR DE SERVICIO
        - Cita debe estar PROGRAMADA o EN_ESPERA_INGRESO
        - NO permitir si estÃ¡ EN_PROCESO o FINALIZADA
        - Todos los servicios deben pertenecer al plan de la cita
        - Deben estar libres (no en otra cita activa)
        
        LÃ³gica:
        1. Validar estado y servicios
        2. Liberar CitaDetalles anteriores
        3. Crear nuevos CitaDetalles
        4. Recalcular duraciÃ³n y segmentos
        5. Actualizar motivo y observaciones
        6. AuditorÃ­a
        """
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import (
            AjustarServiciosRecepcionSerializer,
            CitaRecepcionOperativaDetalleSerializer
        )
        
        cita = self.get_object()
        self.check_object_permissions(request, cita)
        
        # Validar y serializar
        serializer = AjustarServiciosRecepcionSerializer(
            data=request.data,
            context={
                "request": request,
                "empresa": self.request.tenant,
                "usuario_autenticado": request.user
            }
        )
        
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        servicios_ids = serializer.validated_data.get("servicios_plan_detalle_ids", [])
        motivo_visita = serializer.validated_data.get("motivo_visita", None)
        observaciones_cliente = serializer.validated_data.get("observaciones_cliente", None)
        
        try:
            cita_actualizada = CitasRecepcionService.ajustar_servicios_en_recepcion(
                cita=cita,
                usuario=request.user,
                empresa=self.request.tenant,
                servicios_plan_detalle_ids=servicios_ids,
                motivo_visita=motivo_visita,
                observaciones_cliente=observaciones_cliente
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer_respuesta = CitaRecepcionOperativaDetalleSerializer(
            cita_actualizada,
            context={"request": request}
        )
        return Response(serializer_respuesta.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="marcar-en-proceso"
    )
    def marcar_en_proceso(self, request, pk=None, **kwargs):
        """
        POST /api/{slug}/citas/{id}/marcar-en-proceso/
        
        Marcar una cita como EN_PROCESO (inicio de trabajos).
        
        Payload (opcional):
        {
            "llegada_real_at": "2026-03-25T10:15:00Z"  (opcional)
        }
        
        Validaciones:
        - Solo ADMIN o ASESOR DE SERVICIO
        - Cita debe estar PROGRAMADA o EN_ESPERA_INGRESO
        
        LÃ³gica:
        1. Si llegada_real_at no existe, guardarla (payload o timezone.now())
        2. Cambiar estado a EN_PROCESO
        3. NO tocar finalizada_at ni vehiculo_devuelto_at
        """
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaDetalleSerializer
        
        cita = self.get_object()
        self.check_object_permissions(request, cita)
        
        # Extraer parÃ¡metro opcional
        llegada_real_at = request.data.get("llegada_real_at", None)
        if llegada_real_at:
            try:
                from datetime import datetime
                llegada_real_at = datetime.fromisoformat(
                    str(llegada_real_at).replace("Z", "+00:00")
                )
                if timezone.is_naive(llegada_real_at):
                    llegada_real_at = timezone.make_aware(llegada_real_at)
            except (ValueError, TypeError):
                return Response(
                    {"error": "Formato de fecha invÃ¡lido para llegada_real_at"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            cita_actualizada = CitasRecepcionService.marcar_en_proceso(
                cita=cita,
                usuario=request.user,
                empresa=self.request.tenant,
                llegada_real_at=llegada_real_at
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CitaRecepcionOperativaDetalleSerializer(
            cita_actualizada,
            context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["post"],
        url_path="marcar-vehiculo-devuelto"
    )
    def marcar_vehiculo_devuelto(self, request, pk=None, **kwargs):
        """
        POST /api/{slug}/citas/{id}/marcar-vehiculo-devuelto/
        
        Registrar que el cliente recogiÃ³ el vehÃ­culo.
        
        Payload (opcional):
        {
            "vehiculo_devuelto_at": "2026-03-25T14:30:00Z"  (opcional, default: timezone.now())
        }
        
        Validaciones:
        - Solo ADMIN o ASESOR DE SERVICIO
        - Cita debe estar FINALIZADA (finalizada_at no es null)
        - NO permitir marcar dos veces
        
        LÃ³gica:
        1. Validar que cita estÃ¡ finalizada
        2. Si vehiculo_devuelto_at existe, error 400
        3. Guardar vehiculo_devuelto_at (payload o timezone.now())
        4. NO tocar finalizada_at
        """
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        from modulos.vehiculos_servicios_plan_citas.serializers.taller import CitaRecepcionOperativaDetalleSerializer
        
        cita = self.get_object()
        self.check_object_permissions(request, cita)
        
        # Extraer parÃ¡metro opcional
        vehiculo_devuelto_at = request.data.get("vehiculo_devuelto_at", None)
        if vehiculo_devuelto_at:
            try:
                from datetime import datetime
                vehiculo_devuelto_at = datetime.fromisoformat(
                    str(vehiculo_devuelto_at).replace("Z", "+00:00")
                )
                if timezone.is_naive(vehiculo_devuelto_at):
                    vehiculo_devuelto_at = timezone.make_aware(vehiculo_devuelto_at)
            except (ValueError, TypeError):
                return Response(
                    {"error": "Formato de fecha invÃ¡lido para vehiculo_devuelto_at"},
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        try:
            cita_actualizada = CitasRecepcionService.marcar_vehiculo_devuelto(
                cita=cita,
                usuario=request.user,
                empresa=self.request.tenant,
                vehiculo_devuelto_at=vehiculo_devuelto_at
            )
        except ValidationError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = CitaRecepcionOperativaDetalleSerializer(
            cita_actualizada,
            context={"request": request}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    # ========== MÃ‰TODOS PRIVADOS PARA VALIDACIÃ“N DE DISPONIBILIDAD ==========

    def _parse_datetime(self, value):
        """
        Convierte un string ISO a datetime aware.
        """
        from datetime import datetime
        if isinstance(value, datetime):
            dt = value
        else:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt)

        return dt

    def _serializar_segmentos(self, segmentos):
        """
        Devuelve segmentos serializables para respuesta JSON.
        """
        resultado = []
        for idx, seg in enumerate(segmentos, 1):
            resultado.append(
                {
                    "numero": idx,
                    "inicio": seg["inicio_dt"].isoformat(),
                    "fin": seg["fin_dt"].isoformat(),
                    "duracion_min": seg["duracion_min"],
                }
            )
        return resultado

    def _serializar_cita_agenda(self, cita):
        servicios = []
        for d in cita.detalles.all():
            nombre = d.servicio_catalogo.nombre if d.servicio_catalogo else "Servicio"
            servicios.append(
                {
                    "id": str(d.id),
                    "nombre": nombre,
                    "duracion_min": d.tiempo_estandar_min,
                    "estado": d.estado,
                }
            )

        segmentos = []
        for s in cita.espacios_segmentos.all().order_by("orden_segmento"):
            segmentos.append(
                {
                    "id": str(s.id),
                    "espacio_id": str(s.espacio_trabajo_id) if s.espacio_trabajo_id else None,
                    "espacio_nombre": s.espacio_trabajo.nombre if s.espacio_trabajo else "Sin espacio",
                    "inicio": s.inicio_programado.isoformat(),
                    "fin": s.fin_programado.isoformat(),
                }
            )

        return {
            "id": str(cita.id),
            "estado": cita.estado,
            "estado_display": cita.get_estado_display(),
            "inicio": cita.fecha_hora_inicio_programada.isoformat(),
            "fin": cita.fecha_hora_fin_programada.isoformat(),
            "vehiculo_placa": cita.vehiculo.placa if cita.vehiculo else None,
            "cliente_nombre": cita.cliente.nombres if cita.cliente else None,
            "asesor_nombre": cita.asesor_responsable.nombres if cita.asesor_responsable else None,
            "motivo_visita": cita.motivo_visita,
            "servicios": servicios,
            "segmentos": segmentos,
        }

    def _construir_capacidad_agenda(self, empresa, fecha_inicio, fecha_fin, espacio_id=None):
        from datetime import datetime, time, timedelta

        espacios_qs = EspacioTrabajo.objects.filter(empresa=empresa, activo=True)
        if espacio_id:
            espacios_qs = espacios_qs.filter(id=espacio_id)
        espacios = list(espacios_qs)

        resultado = []
        for espacio in espacios:
            horarios = HorarioEspacioTrabajo.objects.filter(
                empresa=empresa,
                espacio_trabajo=espacio,
                activo=True,
            )
            planificable = horarios.exists()
            capacidad_min = 0
            ocupacion_min = 0

            if planificable:
                current = fecha_inicio
                while current <= fecha_fin:
                    dia = current.weekday()
                    horarios_dia = horarios.filter(dia_semana=dia)
                    for h in horarios_dia:
                        ini = h.hora_inicio.hour * 60 + h.hora_inicio.minute
                        fin = h.hora_fin.hour * 60 + h.hora_fin.minute
                        if fin > ini:
                            capacidad_min += fin - ini
                    current += timedelta(days=1)

                ini_dt = timezone.make_aware(datetime.combine(fecha_inicio, time.min))
                fin_dt = timezone.make_aware(datetime.combine(fecha_fin + timedelta(days=1), time.min))
                segmentos = CitaEspacioSegmento.objects.filter(
                    empresa=empresa,
                    espacio_trabajo=espacio,
                    inicio_programado__lt=fin_dt,
                    fin_programado__gt=ini_dt,
                    cita__estado__in=[EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO],
                )
                for seg in segmentos:
                    inicio = max(seg.inicio_programado, ini_dt)
                    fin = min(seg.fin_programado, fin_dt)
                    if fin > inicio:
                        ocupacion_min += int((fin - inicio).total_seconds() // 60)

            disponible_min = max(capacidad_min - ocupacion_min, 0)
            porcentaje = round((ocupacion_min * 100 / capacidad_min), 2) if capacidad_min > 0 else 0

            resultado.append(
                {
                    "espacio_id": str(espacio.id),
                    "espacio_nombre": espacio.nombre,
                    "tipo": espacio.tipo,
                    "planificable": planificable,
                    "capacidad_min": capacidad_min,
                    "ocupacion_min": ocupacion_min,
                    "disponible_min": disponible_min,
                    "ocupacion_pct": porcentaje,
                }
            )

        return resultado

