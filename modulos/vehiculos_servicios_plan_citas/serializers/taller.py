""" Serializers base para modelos del taller automotriz.
Estructura:
- Serializers relacionados con vehÃ­culos y planes
- Serializers para catÃ¡logos
- Serializers para citas"""

from rest_framework import serializers
from django.utils import timezone
from modulos.administracion_acceso_configuracion.serializers.usuarios import UsuarioPropietarioSerializer
from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.vehiculos_servicios_plan_citas.models import (
    Vehiculo,
    PlanServicioVehiculo,
    PlanServicioDetalle,
    ServicioCatalogo,
    OrigenPlanServicioDetalle,
    EstadoPlanServicioDetalle,
    EspacioTrabajo,
    HorarioEspacioTrabajo,
    Cita,
    CitaDetalle,
    CitaEspacioSegmento,
    EstadoVehiculo,
    TipoSegmentoCitaEspacio,
    EstadoSegmentoCitaEspacio,
    EstadoCita,
    CanalOrigenCita,
)
from modulos.atencion_tecnica_ejecucion.models import (
    AvanceVehiculo,
    PresupuestoCita,
    PresupuestoDetalle,
    OrdenTrabajoGlobal,
    OrdenTrabajoDetalle,
    OrdenTrabajoGlobalMecanico,
)
from modulos.inventario_proveedores_administracion.models import (
    CategoriaInventario,
    ItemInventario,
    Proveedor,
    Compra,
    CompraDetalle,
    MovimientoInventario,
    SolicitudRepuesto,
    SolicitudRepuestoDetalle,
    VentaMostrador,
    VentaMostradorDetalle,
    PagoTaller,
    Factura,
    CajaUsuario,
    MovimientoCaja,
)
from modulos.comunicacion_control_inteligencia.models import (
    Notificacion,
    NotificacionEntrega,
    ConversacionIA,
    MensajeIA,
    AccionIA,
    ReporteGenerado,
)
from modulos.vehiculos_servicios_plan_citas.services.bloques_tiempo import (
    BLOQUE_MINUTOS,
    es_bloque_valido,
)


# ============================================================================
# SERIALIZERS - VEHÃCULOS Y PLANES
# ============================================================================

class VehiculoSerializer(serializers.ModelSerializer):
    """Serializer base para VehÃ­culo."""
    propietario_nombres = serializers.CharField(
        source="propietario.nombres",
        read_only=True
    )

    class Meta:
        model = Vehiculo
        fields = [
            "id",
            "empresa",
            "propietario",
            "propietario_nombres",
            "placa",
            "marca",
            "modelo",
            "anio",
            "color",
            "kilometraje_actual",
            "vin_chasis",
            "motor",
            "observaciones",
            "estado",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ============================================================================
# SERIALIZERS ESPECÃFICOS PARA CU14 - GESTIONAR VEHÃCULOS
# ============================================================================

class VehiculoListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar vehÃ­culos.
    Incluye datos del propietario (objeto anidado con nombres, apellidos, email) y estado.
    TambiÃ©n incluye el ID del plan de servicio asociado si existe.
    """
    propietario = UsuarioPropietarioSerializer(read_only=True)
    plan_servicio_id = serializers.SerializerMethodField()
    
    def get_plan_servicio_id(self, obj):
        """Retorna el ID del plan de servicio si existe."""
        if hasattr(obj, 'plan_servicio') and obj.plan_servicio:
            return str(obj.plan_servicio.id)
        return None
    
    class Meta:
        model = Vehiculo
        fields = [
            "id",
            "placa",
            "marca",
            "modelo",
            "anio",
            "color",
            "propietario",
            "estado",
            "plan_servicio_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class VehiculoDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para detalle de un vehÃ­culo.
    Incluye todos los campos disponibles.
    """
    propietario_nombres = serializers.CharField(
        source="propietario.nombres",
        read_only=True
    )
    propietario_email = serializers.CharField(
        source="propietario.email",
        read_only=True
    )
    propietario_telefono = serializers.CharField(
        source="propietario.telefono",
        read_only=True
    )
    
    class Meta:
        model = Vehiculo
        fields = [
            "id",
            "empresa",
            "propietario",
            "propietario_nombres",
            "propietario_email",
            "propietario_telefono",
            "placa",
            "marca",
            "modelo",
            "anio",
            "color",
            "kilometraje_actual",
            "vin_chasis",
            "motor",
            "observaciones",
            "estado",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "empresa", "created_at", "updated_at"]


class VehiculoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un vehÃ­culo.
    
    Comportamiento segÃºn rol:
    - Cliente: No puede especificar propietario (se asigna automÃ¡ticamente)
    - Asesor de Servicio/Admin: Puede especificar propietario
    
    Validaciones:
    - Placa Ãºnica por empresa
    - Propietario debe pertenecer a la misma empresa
    """
    propietario_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="UUID del propietario del vehÃ­culo (solo para asesor de servicio/admin)"
    )
    
    class Meta:
        model = Vehiculo
        fields = [
            "propietario_id",
            "placa",
            "marca",
            "modelo",
            "anio",
            "color",
            "kilometraje_actual",
            "vin_chasis",
            "motor",
            "observaciones",
        ]
    
    def validate_placa(self, value):
        """Validar que la placa sea Ãºnica por empresa."""
        empresa = self.context.get("empresa")
        
        if empresa and Vehiculo.objects.filter(
            empresa=empresa,
            placa=value
        ).exists():
            raise serializers.ValidationError(
                f"Un vehÃ­culo con placa '{value}' ya existe en esta empresa."
            )
        
        return value
    
    def validate(self, data):
        """Validar el objeto completo."""
        empresa = self.context.get("empresa")
        usuario_autenticado = self.context.get("usuario_autenticado")
        propietario_id = data.get("propietario_id")
        rol_nombre = usuario_autenticado.rol.nombre if usuario_autenticado and usuario_autenticado.rol else None
        
        # ADMIN y ASESOR DE SERVICIO: propietario_id es OBLIGATORIO
        if rol_nombre in ["ADMIN", "ASESOR DE SERVICIO"]:
            if not propietario_id:
                raise serializers.ValidationError(
                    {"propietario_id": "Los administradores y asesores deben especificar el propietario explÃ­citamente."}
                )
        
        # USUARIO: propietario_id es opcional (se inferirÃ¡ como el mismo usuario)
        # Si especifica, validar que sea a sÃ­ mismo
        if propietario_id:
            if rol_nombre == "USUARIO" and propietario_id != usuario_autenticado.id:
                raise serializers.ValidationError(
                    {"propietario_id": "Los clientes solo pueden registrar vehÃ­culos a su nombre."}
                )
            
            # Validar que el propietario existe y pertenece a la empresa
            try:
                propietario = Usuario.objects.get(id=propietario_id, empresa=empresa)
                data["propietario_id"] = propietario  # Reemplazar UUID por instancia
            except Usuario.DoesNotExist:
                raise serializers.ValidationError(
                    {"propietario_id": "El propietario especificado no existe en esta empresa."}
                )
        
        return data
    
    def create(self, validated_data):
        """Crear vehÃ­culo con propietario automÃ¡tico si es cliente."""
        empresa = self.context.get("empresa")
        usuario_autenticado = self.context.get("usuario_autenticado")
        
        # Si no especifica propietario, usar el usuario autenticado
        propietario = validated_data.pop("propietario_id", None)
        if not propietario and usuario_autenticado:
            propietario = usuario_autenticado
        
        vehiculo = Vehiculo.objects.create(
            empresa=empresa,
            propietario=propietario,
            **validated_data
        )
        
        return vehiculo


class VehiculoEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un vehÃ­culo (solo asesor de servicio/admin).
    
    Campos permitidos:
    - marca, modelo, anio, color
    - kilometraje_actual, vin_chasis, motor
    - observaciones
    - propietario (solo para ediciÃ³n autorizada)
    
    No se puede editar:
    - empresa
    - placa (una vez creado)
    - estado (usar endpoint especÃ­fico)
    """
    propietario_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="UUID del nuevo propietario del vehÃ­culo"
    )
    
    class Meta:
        model = Vehiculo
        fields = [
            "propietario_id",
            "marca",
            "modelo",
            "anio",
            "color",
            "kilometraje_actual",
            "vin_chasis",
            "motor",
            "observaciones",
        ]
    
    def validate(self, data):
        """Validar que el propietario pertenezca a la misma empresa."""
        empresa = self.context.get("empresa")
        propietario_id = data.get("propietario_id")
        
        if propietario_id:
            # Validar que el propietario existe y pertenece a la empresa
            try:
                propietario = Usuario.objects.get(id=propietario_id, empresa=empresa)
                data["propietario_id"] = propietario  # Reemplazar UUID por instancia
            except Usuario.DoesNotExist:
                raise serializers.ValidationError(
                    "El propietario especificado no existe en esta empresa."
                )
        
        return data
    
    def update(self, instance, validated_data):
        """Actualizar vehÃ­culo."""
        propietario = validated_data.pop("propietario_id", None)
        
        if propietario is not None:
            instance.propietario = propietario
        
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        instance.save()
        return instance


class VehiculoEstadoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar el estado de un vehÃ­culo (activar/inactivar).
    
    Solo acepta cambios entre ACTIVO e INACTIVO.
    Incluye un campo 'motivo' para registrar por quÃ© se cambiÃ³ el estado.
    """
    motivo = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        write_only=True,
        help_text="Motivo del cambio de estado"
    )
    
    class Meta:
        model = Vehiculo
        fields = [
            "estado",
            "motivo",
        ]
    
    def validate_estado(self, value):
        """Validar que el estado sea vÃ¡lido."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoVehiculo
        
        if value not in [EstadoVehiculo.ACTIVO, EstadoVehiculo.INACTIVO]:
            raise serializers.ValidationError(
                f"Estado invÃ¡lido. Valores permitidos: {EstadoVehiculo.ACTIVO}, {EstadoVehiculo.INACTIVO}"
            )
        
        return value
    
    def update(self, instance, validated_data):
        """Actualizar solo el estado, ignorar motivo en el modelo (se guarda en auditorÃ­a)."""
        instance.estado = validated_data.get("estado", instance.estado)
        instance.save()
        return instance


class PlanServicioDetalleSerializer(serializers.ModelSerializer):
    """Serializer base para detalle de plan de servicio."""
    servicio_nombre = serializers.CharField(
        source="servicio_catalogo.nombre",
        read_only=True
    )

    class Meta:
        model = PlanServicioDetalle
        fields = [
            "id",
            "empresa",
            "plan_servicio",
            "servicio_catalogo",
            "servicio_nombre",
            "estado",
            "origen",
            "prioridad",
            "tiempo_estandar_min",
            "precio_referencial",
            "observaciones",
            "recomendado_por",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class PlanServicioVehiculoSerializer(serializers.ModelSerializer):
    """Serializer base para Plan de Servicio del VehÃ­culo."""
    detalles = PlanServicioDetalleSerializer(many=True, read_only=True)
    vehiculo_placa = serializers.StringRelatedField(
        source="vehiculo.placa",
        read_only=True
    )

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "id",
            "empresa",
            "vehiculo",
            "vehiculo_placa",
            "estado",
            "descripcion_general",
            "creado_por",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ============================================================================
# SERIALIZERS ESPECIALIZADOS - PLANES DE VEHÃCULOS (CU22)
# ============================================================================

class PlanServicioVehiculoListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar planes de vehÃ­culos (vista simplificada).
    """
    vehiculo = serializers.SerializerMethodField()
    cantidad_detalles = serializers.SerializerMethodField()
    cantidad_pendientes = serializers.SerializerMethodField()

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "id",
            "vehiculo",
            "estado",
            "cantidad_detalles",
            "cantidad_pendientes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    
    def get_vehiculo(self, obj):
        """InformaciÃ³n completa del vehÃ­culo incluyendo propietario."""
        propietario_nombres = "N/A"
        if obj.vehiculo.propietario:
            nombres = obj.vehiculo.propietario.nombres or ""
            apellidos = obj.vehiculo.propietario.apellidos or ""
            propietario_nombres = f"{nombres} {apellidos}".strip()
        
        return {
            "id": str(obj.vehiculo.id),
            "placa": obj.vehiculo.placa,
            "marca": obj.vehiculo.marca,
            "modelo": obj.vehiculo.modelo,
            "propietario": {
                "id": str(obj.vehiculo.propietario.id) if obj.vehiculo.propietario else None,
                "nombres": propietario_nombres,
            } if obj.vehiculo.propietario else None,
        }
    
    def get_cantidad_detalles(self, obj):
        """Total de detalles en el plan."""
        return obj.detalles.count()
    
    def get_cantidad_pendientes(self, obj):
        """Cantidad de detalles pendientes."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoPlanServicioDetalle
        return obj.detalles.filter(estado=EstadoPlanServicioDetalle.PENDIENTE).count()


class PlanServicioVehiculoDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para detalle completo de un plan de vehÃ­culo.
    Incluye todos los datos del plan y sus detalles.
    """
    vehiculo_info = serializers.SerializerMethodField()
    creado_por_nombre = serializers.CharField(
        source="creado_por.nombres",
        read_only=True
    )
    detalles = PlanServicioDetalleSerializer(many=True, read_only=True)

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "id",
            "empresa",
            "vehiculo",
            "vehiculo_info",
            "estado",
            "descripcion_general",
            "creado_por",
            "creado_por_nombre",
            "detalles",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "empresa", "created_at", "updated_at"]
    
    def get_vehiculo_info(self, obj):
        """InformaciÃ³n completa del vehÃ­culo."""
        return {
            "id": str(obj.vehiculo.id),
            "placa": obj.vehiculo.placa,
            "marca": obj.vehiculo.marca,
            "modelo": obj.vehiculo.modelo,
            "anio": obj.vehiculo.anio,
            "propietario": obj.vehiculo.propietario.nombres if obj.vehiculo.propietario else None,
        }


class PlanServicioVehiculoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un nuevo plan de vehÃ­culo.
    
    Validaciones:
    - vehiculo_id debe existir y pertenecer a la empresa
    - El vehÃ­culo debe estar activo
    """
    vehiculo_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "vehiculo_id",
            "descripcion_general",
        ]
    
    def validate_vehiculo_id(self, value):
        """Validar que el vehÃ­culo existe y pertenece a la empresa."""
        empresa = self.context.get("empresa")
        
        try:
            vehiculo = Vehiculo.objects.get(id=value, empresa=empresa)
        except Vehiculo.DoesNotExist:
            raise serializers.ValidationError(
                "El vehÃ­culo especificado no existe en esta empresa."
            )
        
        from modulos.vehiculos_servicios_plan_citas.models import EstadoVehiculo
        if vehiculo.estado != EstadoVehiculo.ACTIVO:
            raise serializers.ValidationError(
                "El vehÃ­culo debe estar activo para crear un plan."
            )
        
        return vehiculo

    def create(self, validated_data):
        """Crear plan de vehÃ­culo."""
        empresa = self.context.get("empresa")
        usuario = self.context.get("usuario_autenticado")
        
        return PlanServicioVehiculo.objects.create(
            empresa=empresa,
            vehiculo=validated_data["vehiculo_id"],
            creado_por=usuario,
            descripcion_general=validated_data.get("descripcion_general", ""),
        )


class PlanServicioVehiculoEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un plan de vehÃ­culo existente.
    
    Solo permite editar:
    - descripcion_general
    """

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "descripcion_general",
        ]


class PlanServicioVehiculoEstadoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar estado de un plan de vehÃ­culo.
    
    Permite transiciones vÃ¡lidas entre estados del plan.
    """
    motivo = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        write_only=True,
        help_text="Motivo del cambio de estado"
    )

    class Meta:
        model = PlanServicioVehiculo
        fields = [
            "estado",
            "motivo",
        ]


class PlanServicioDetalleListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar detalles de un plan (vista simplificada).
    """
    servicio_info = serializers.SerializerMethodField()
    recomendado_por_nombre = serializers.CharField(
        source="recomendado_por.nombres",
        read_only=True,
        allow_null=True
    )

    class Meta:
        model = PlanServicioDetalle
        fields = [
            "id",
            "plan_servicio",
            "servicio_info",
            "estado",
            "origen",
            "prioridad",
            "recomendado_por_nombre",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]
    
    def get_servicio_info(self, obj):
        """InformaciÃ³n condensada del servicio."""
        if not obj.servicio_catalogo:
            return None
        return {
            "id": str(obj.servicio_catalogo.id),
            "nombre": obj.servicio_catalogo.nombre,
            "precio_base": float(obj.servicio_catalogo.precio_base),
        }


class PlanServicioDetalleCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para agregar un nuevo detalle a un plan.
    
    REGLA NUEVA (CU22 - CatÃ¡logo Obligatorio):
    - servicio_catalogo_id es OBLIGATORIO
    - origen se detecta automÃ¡ticamente desde request.user.rol.nombre
    - tiempo_estandar_min se obtiene del servicio catÃ¡logo
    - precio_referencial se obtiene del servicio catÃ¡logo
    - estado inicial se asigna segÃºn origen (MECANICO â†’ RECOMENDADO, otros â†’ PENDIENTE)
    
    El cliente SOLO debe enviar:
    - servicio_catalogo_id (obligatorio)
    - prioridad (opcional, default MEDIA)
    - observaciones (opcional)
    """
    plan_servicio_id = serializers.UUIDField(write_only=True)
    servicio_catalogo_id = serializers.UUIDField(
        required=True,
        write_only=True,
        help_text="Servicio catÃ¡logo obligatorio"
    )

    class Meta:
        model = PlanServicioDetalle
        fields = [
            "plan_servicio_id",
            "servicio_catalogo_id",
            "prioridad",
            "observaciones",
        ]

    def validate_plan_servicio_id(self, value):
        """Validar que el plan existe y pertenece a la empresa."""
        empresa = self.context.get("empresa")
        
        try:
            plan = PlanServicioVehiculo.objects.get(id=value, empresa=empresa)
        except PlanServicioVehiculo.DoesNotExist:
            raise serializers.ValidationError(
                "El plan de vehÃ­culo especificado no existe en esta empresa."
            )
        
        return plan

    def validate_servicio_catalogo_id(self, value):
        """Validar que el servicio existe, pertenece a la empresa y estÃ¡ activo."""
        empresa = self.context.get("empresa")
        
        try:
            servicio = ServicioCatalogo.objects.get(
                id=value, 
                empresa=empresa,
                activo=True
            )
        except ServicioCatalogo.DoesNotExist:
            raise serializers.ValidationError(
                "El servicio catÃ¡logo no existe, no pertenece a esta empresa o no estÃ¡ activo."
            )
        
        return servicio

    def validate(self, data):
        """
        Validaciones finales:
        1. Validar que el plan existe y pertenece a la empresa
        2. Detectar origen desde usuario autenticado
        3. Determinar estado inicial segÃºn el origen detectado
        
        NUEVO FLUJO:
        - origen NO viene del frontend, se detecta automÃ¡ticamente
        - tiempo_estandar_min NO viene del frontend, se obtiene del servicio
        - precio_referencial NO viene del frontend, se obtiene del servicio
        """
        plan = data.get("plan_servicio_id")
        servicio = data.get("servicio_catalogo_id")
        
        # El servicio es obligatorio en el nuevo flujo
        if not servicio:
            raise serializers.ValidationError(
                {"servicio_catalogo_id": "El servicio catÃ¡logo es obligatorio."}
            )
        
        # Detectar origen desde el usuario autenticado
        usuario = self.context.get("usuario_autenticado")
        if not usuario:
            raise serializers.ValidationError(
                "Usuario autenticado no disponible en contexto."
            )
        
        # Obtener nombre del rol de forma defensiva
        rol_nombre = None
        try:
            if usuario.rol:
                rol_nombre = usuario.rol.nombre
        except AttributeError:
            rol_nombre = None
        
        if not rol_nombre:
            rol_nombre = "ASESOR"
        
        # Mapear rol a origen
        if rol_nombre == "USUARIO":
            origen_detectado = OrigenPlanServicioDetalle.CLIENTE
        elif rol_nombre == "MECÃNICO":
            origen_detectado = OrigenPlanServicioDetalle.MECANICO
        elif rol_nombre == "ADMIN":
            origen_detectado = OrigenPlanServicioDetalle.ADMIN
        else:  # ASESOR DE SERVICIO, otros
            origen_detectado = OrigenPlanServicioDetalle.ASESOR
        
        # Asignar origen detectado y estado inicial
        data["_origen_detectado"] = origen_detectado
        
        if origen_detectado == OrigenPlanServicioDetalle.MECANICO:
            data["_estado_asignado"] = EstadoPlanServicioDetalle.RECOMENDADO
        else:  # CLIENTE o ASESOR
            data["_estado_asignado"] = EstadoPlanServicioDetalle.PENDIENTE
        
        # Obtener tiempo y precio del servicio catÃ¡logo
        if servicio.tiempo_estandar_min < BLOQUE_MINUTOS or servicio.tiempo_estandar_min % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                {"servicio_catalogo_id": "El servicio seleccionado no estÃ¡ configurado en bloques de 30 minutos."}
            )
        data["_tiempo_desde_catalogo"] = servicio.tiempo_estandar_min
        data["_precio_desde_catalogo"] = servicio.precio_base
        
        return data

    def create(self, validated_data):
        """
        Crear detalle de plan.
        
        NUEVO FLUJO (CU22 - CatÃ¡logo Obligatorio):
        1. Obtener valores detectados en validate()
        2. origen tiene que ser SIEMPRE el detectado (no desde frontend)
        3. tiempo y precio siempre del catÃ¡logo
        4. estado inicial siempre asignado segÃºn origen
        5. Si origen es MECANICO, asignar recomendado_por al usuario autenticado
        """
        empresa = self.context.get("empresa")
        usuario = self.context.get("usuario_autenticado")
        
        if not empresa:
            raise serializers.ValidationError("Empresa no disponible en contexto.")
        
        plan = validated_data.pop("plan_servicio_id", None)
        servicio = validated_data.pop("servicio_catalogo_id", None)
        
        if not plan or not servicio:
            raise serializers.ValidationError("Plan y servicio son requeridos.")
        
        # Valores detectados / obtenidos en validate()
        origen_detectado = validated_data.pop("_origen_detectado", None)
        estado_asignado = validated_data.pop("_estado_asignado", None)
        tiempo_desde_catalogo = validated_data.pop("_tiempo_desde_catalogo", None)
        precio_desde_catalogo = validated_data.pop("_precio_desde_catalogo", None)
        
        if not origen_detectado or not estado_asignado:
            raise serializers.ValidationError("Valores detectados no disponibles en validaciÃ³n.")
        
        # Asignar recomendado_por si es mecÃ¡nico
        if origen_detectado == OrigenPlanServicioDetalle.MECANICO:
            validated_data["recomendado_por"] = usuario
        else:
            validated_data["recomendado_por"] = None
        
        # Crear con valores finales
        return PlanServicioDetalle.objects.create(
            empresa=empresa,
            plan_servicio=plan,
            servicio_catalogo=servicio,
            origen=origen_detectado,
            tiempo_estandar_min=tiempo_desde_catalogo,
            precio_referencial=precio_desde_catalogo,
            estado=estado_asignado,
            **validated_data
        )


class PlanServicioDetalleEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un detalle de plan existente.
    
    Permite editar:
    - prioridad
    - observaciones
    - precio_referencial
    - tiempo_estandar_min
    """

    class Meta:
        model = PlanServicioDetalle
        fields = [
            "prioridad",
            "tiempo_estandar_min",
            "precio_referencial",
            "observaciones",
        ]

    def validate_tiempo_estandar_min(self, value):
        """Validar que el tiempo estÃ¡ndar sea mÃºltiplo de 30 min."""
        if value < BLOQUE_MINUTOS:
            raise serializers.ValidationError("La duraciÃ³n mÃ­nima es 30 minutos.")
        if value % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                "La duraciÃ³n debe seleccionarse en bloques de 30 minutos."
            )
        return value


class PlanServicioDetalleEstadoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar estado de un detalle del plan.
    
    Permite transiciones vÃ¡lidas entre estados del detalle.
    """
    motivo = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        write_only=True,
        help_text="Motivo del cambio de estado"
    )

    class Meta:
        model = PlanServicioDetalle
        fields = [
            "estado",
            "motivo",
        ]


class ServicioCatalogoSerializer(serializers.ModelSerializer):
    """Serializer base para Servicio CatÃ¡logo."""

    class Meta:
        model = ServicioCatalogo
        fields = [
            "id",
            "empresa",
            "codigo",
            "nombre",
            "descripcion",
            "tiempo_estandar_min",
            "precio_base",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ============================================================================
# RE-IMPORTS FROM ESPACIOS MODULE
# ============================================================================

from modulos.vehiculos_servicios_plan_citas.serializers.espacios import (
    HorarioEspacioTrabajoSerializer,
    EspacioTrabajoSerializer,
)


# ============================================================================
# SERIALIZERS - CITAS
# ============================================================================

class CitaEspacioSegmentoSerializer(serializers.ModelSerializer):
    """Serializer base para Segmento Cita-Espacio."""
    espacio_nombre = serializers.CharField(
        source="espacio_trabajo.nombre",
        read_only=True
    )

    class Meta:
        model = CitaEspacioSegmento
        fields = [
            "id",
            "empresa",
            "cita",
            "espacio_trabajo",
            "espacio_nombre",
            "orden_segmento",
            "tipo_segmento",
            "estado_segmento",
            "inicio_programado",
            "fin_programado",
            "inicio_real",
            "fin_real",
            "motivo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class CitaSerializer(serializers.ModelSerializer):
    """Serializer base para Cita."""
    espacios_segmentos = CitaEspacioSegmentoSerializer(many=True, read_only=True)
    vehiculo_placa = serializers.CharField(
        source="vehiculo.placa",
        read_only=True
    )

    class Meta:
        model = Cita
        fields = [
            "id",
            "empresa",
            "vehiculo",
            "vehiculo_placa",
            "cliente",
            "plan_servicio",
            "estado",
            "canal_origen",
            "fecha_hora_inicio_programada",
            "fecha_hora_fin_programada",
            "duracion_estimada_min",
            "llegada_real_at",
            "reprogramaciones_count",
            "motivo_visita",
            "observaciones_cliente",
            "asesor_responsable",
            "espacios_segmentos",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class AvanceVehiculoSerializer(serializers.ModelSerializer):
    """Serializer base para Avance VehÃ­culo."""

    class Meta:
        model = AvanceVehiculo
        fields = [
            "id",
            "empresa",
            "cita",
            "orden_detalle",
            "registrado_por",
            "tipo",
            "estado_nuevo",
            "mensaje",
            "porcentaje_avance",
            "visible_cliente",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


# ============================================================================
# RE-IMPORTS FROM SEPARATED MODULES
# ============================================================================

from modulos.atencion_tecnica_ejecucion.serializers.presupuestos import (
    PresupuestoDetalleSerializer,
    PresupuestoCitaSerializer,
)
from modulos.atencion_tecnica_ejecucion.serializers.ordenes_trabajo import (
    OrdenTrabajoDetalleSerializer,
    OrdenTrabajoGlobalMecanicoSerializer,
    OrdenTrabajoGlobalSerializer,
)
from modulos.inventario_proveedores_administracion.serializers.inventario import (
    CategoriaInventarioSerializer,
    ItemInventarioSerializer,
    ProveedorSerializer,
    CompraDetalleSerializer,
    CompraSerializer,
    MovimientoInventarioSerializer,
)
from modulos.inventario_proveedores_administracion.serializers.solicitudes import (
    SolicitudRepuestoDetalleSerializer,
    SolicitudRepuestoSerializer,
)
from modulos.inventario_proveedores_administracion.serializers.ventas_pagos import (
    VentaMostradorDetalleSerializer,
    VentaMostradorSerializer,
    PagoTallerSerializer,
    FacturaSerializer,
    CajaUsuarioSerializer,
    MovimientoCajaSerializer,
)
from modulos.comunicacion_control_inteligencia.serializers.notificaciones import (
    NotificacionEntregaSerializer,
    NotificacionSerializer,
)
from modulos.comunicacion_control_inteligencia.serializers.ia import (
    ConversacionIASerializer,
    MensajeIASerializer,
    AccionIASerializer,
)
from modulos.comunicacion_control_inteligencia.serializers.reportes import (
    ReporteGeneradoSerializer,
)


# ============================================================================
# SERIALIZERS ESPECÃFICOS PARA CU15 - GESTIONAR CATÃLOGO DE SERVICIOS
# ============================================================================

class ServicioCatalogoListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar servicios del catÃ¡logo.
    Retorna informaciÃ³n bÃ¡sica de cada servicio.
    """
    activo_display = serializers.SerializerMethodField()
    
    class Meta:
        model = ServicioCatalogo
        fields = [
            "id",
            "codigo",
            "nombre",
            "descripcion",
            "tiempo_estandar_min",
            "precio_base",
            "activo",
            "activo_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    
    def get_activo_display(self, obj):
        """Retorna versiÃ³n legible del estado activo."""
        return "Activo" if obj.activo else "Inactivo"


class ServicioCatalogoDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para detalle completo de un servicio.
    Incluye tous los campos y metadata de auditorÃ­a.
    """
    activo_display = serializers.SerializerMethodField()
    
    class Meta:
        model = ServicioCatalogo
        fields = [
            "id",
            "empresa",
            "codigo",
            "nombre",
            "descripcion",
            "tiempo_estandar_min",
            "precio_base",
            "activo",
            "activo_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "empresa", "created_at", "updated_at"]
    
    def get_activo_display(self, obj):
        """Retorna versiÃ³n legible del estado activo."""
        return "Activo" if obj.activo else "Inactivo"


class ServicioCatalogoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un nuevo servicio.
    
    Validaciones:
    - CÃ³digo Ãºnico por empresa
    - Nombre obligatorio
    - Tiempo estÃ¡ndar > 0
    - Precio base >= 0
    """
    
    class Meta:
        model = ServicioCatalogo
        fields = [
            "codigo",
            "nombre",
            "descripcion",
            "tiempo_estandar_min",
            "precio_base",
        ]
    
    def validate_codigo(self, value):
        """Validar que el cÃ³digo sea Ãºnico por empresa."""
        empresa = self.context.get("empresa")
        
        if empresa and ServicioCatalogo.objects.filter(
            empresa=empresa,
            codigo=value
        ).exists():
            raise serializers.ValidationError(
                f"Ya existe un servicio con cÃ³digo '{value}' en esta empresa."
            )
        
        return value
    
    def validate_nombre(self, value):
        """Validar que el nombre no sea vacÃ­o."""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "El nombre del servicio es obligatorio."
            )
        return value
    
    def validate_tiempo_estandar_min(self, value):
        """Validar que el tiempo estÃ¡ndar sea mÃºltiplo de 30 min."""
        if value < BLOQUE_MINUTOS:
            raise serializers.ValidationError("La duraciÃ³n mÃ­nima es 30 minutos.")
        if value % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                "La duraciÃ³n debe seleccionarse en bloques de 30 minutos."
            )
        return value
    
    def validate_precio_base(self, value):
        """Validar que el precio base sea vÃ¡lido."""
        if value < 0:
            raise serializers.ValidationError(
                "El precio base no puede ser negativo."
            )
        return value
    
    def create(self, validated_data):
        """Crear servicio asignando empresa automÃ¡ticamente."""
        empresa = self.context.get("empresa")
        servicio = ServicioCatalogo.objects.create(
            empresa=empresa,
            **validated_data
        )
        return servicio


class ServicioCatalogoEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un servicio existente.
    
    Campos permitidos para ediciÃ³n:
    - cÃ³digo
    - nombre
    - descripcion
    - tiempo_estandar_min
    - precio_base
    
    No se puede cambiar:
    - empresa
    - activo (usar endpoint especÃ­fico)
    """
    
    class Meta:
        model = ServicioCatalogo
        fields = [
            "codigo",
            "nombre",
            "descripcion",
            "tiempo_estandar_min",
            "precio_base",
        ]
    
    def validate_codigo(self, value):
        """Validar que el cÃ³digo siga siendo Ãºnico por empresa."""
        empresa = self.context.get("empresa")
        instance = self.instance
        
        # Si el cÃ³digo cambiÃ³, verificar que el nuevo sea Ãºnico
        if instance and instance.codigo != value:
            if empresa and ServicioCatalogo.objects.filter(
                empresa=empresa,
                codigo=value
            ).exists():
                raise serializers.ValidationError(
                    f"Ya existe un servicio con cÃ³digo '{value}' en esta empresa."
                )
        
        return value
    
    def validate_nombre(self, value):
        """Validar que el nombre no sea vacÃ­o."""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "El nombre del servicio es obligatorio."
            )
        return value
    
    def validate_tiempo_estandar_min(self, value):
        """Validar que el tiempo estÃ¡ndar sea mÃºltiplo de 30 min."""
        if value < BLOQUE_MINUTOS:
            raise serializers.ValidationError("La duraciÃ³n mÃ­nima es 30 minutos.")
        if value % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                "La duraciÃ³n debe seleccionarse en bloques de 30 minutos."
            )
        return value
    
    def validate_precio_base(self, value):
        """Validar que el precio base sea vÃ¡lido."""
        if value < 0:
            raise serializers.ValidationError(
                "El precio base no puede ser negativo."
            )
        return value


class ServicioCatalogoEstadoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar el estado (activo/inactivo) de un servicio.
    
    Solo para cambios de estado. El cambio debe ser auditado con motivo.
    """
    motivo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        help_text="Motivo del cambio de estado (opcional)"
    )
    
    class Meta:
        model = ServicioCatalogo
        fields = [
            "activo",
            "motivo",
        ]
    
    def validate(self, data):
        """Validar que el estado cambie."""
        instance = self.instance
        nuevo_estado = data.get("activo")
        
        if instance and instance.activo == nuevo_estado:
            raise serializers.ValidationError(
                f"El servicio ya estÃ¡ {'activo' if nuevo_estado else 'inactivo'}."
            )
        
        return data


# ============================================================================
# RE-IMPORTS FROM ESPACIOS MODULE (SPECIALIZED SERIALIZERS)
# ============================================================================

from modulos.vehiculos_servicios_plan_citas.serializers.espacios import (
    _validar_solapamiento_horario,
    HorarioEspacioTrabajoListadoSerializer,
    HorarioEspacioTrabajoCreacionSerializer,
    HorarioEspacioTrabajoEdicionSerializer,
    HorarioEspacioTrabajoActivoSerializer,
    EspacioTrabajoListadoSerializer,
    EspacioTrabajoDetalleSerializer,
    EspacioTrabajoCreacionSerializer,
    EspacioTrabajoEdicionSerializer,
    EspacioTrabajoEstadoSerializer,
    EspacioTrabajoActivoSerializer,
)


# ============================================================================
# SERIALIZERS - CITAS (CU17)
# ============================================================================

class CitaEspacioSegmentoSerializer(serializers.ModelSerializer):
    """
    Serializer para segmentos de espacio en una cita.
    """
    espacio_trabajo_nombre = serializers.CharField(
        source="espacio_trabajo.nombre",
        read_only=True
    )
    tipo_segmento_display = serializers.SerializerMethodField()
    estado_segmento_display = serializers.SerializerMethodField()
    
    class Meta:
        model = CitaEspacioSegmento
        fields = [
            "id",
            "cita",
            "espacio_trabajo",
            "espacio_trabajo_nombre",
            "orden_segmento",
            "tipo_segmento",
            "tipo_segmento_display",
            "estado_segmento",
            "estado_segmento_display",
            "inicio_programado",
            "fin_programado",
            "inicio_real",
            "fin_real",
            "motivo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "cita", "created_at", "updated_at"]
    
    def get_tipo_segmento_display(self, obj):
        """Retorna descripciÃ³n legible del tipo de segmento."""
        from modulos.vehiculos_servicios_plan_citas.models import TipoSegmentoCitaEspacio
        tipo_map = dict(TipoSegmentoCitaEspacio.choices)
        return tipo_map.get(obj.tipo_segmento, obj.tipo_segmento)
    
    def get_estado_segmento_display(self, obj):
        """Retorna descripciÃ³n legible del estado del segmento."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoSegmentoCitaEspacio
        estado_map = dict(EstadoSegmentoCitaEspacio.choices)
        return estado_map.get(obj.estado_segmento, obj.estado_segmento)


class CitaEspacioSegmentoCreacionSerializer(serializers.Serializer):
    """Serializer para crear segmentos de espacio (uso en validaciÃ³n de cita)."""
    orden_segmento = serializers.IntegerField()
    espacio_trabajo_id = serializers.UUIDField()
    tipo_segmento = serializers.CharField(max_length=20)
    inicio_programado = serializers.DateTimeField()
    fin_programado = serializers.DateTimeField()
    
    def validate(self, data):
        """Validaciones bÃ¡sicas del segmento."""
        if data["inicio_programado"] >= data["fin_programado"]:
            raise serializers.ValidationError("Inicio debe ser anterior a fin del segmento.")
        return data


# ============================================================================
# SERIALIZERS - DETALLE DE CITA (CU18) - DefiniciÃ³n anticipada
# ============================================================================

class CitaDetalleIndividualSerializer(serializers.ModelSerializer):
    """
    Serializer para cada detalle/servicio de una cita.
    Representa un PlanServicioDetalle seleccionado para esa cita.
    """
    servicio_nombre = serializers.CharField(
        source="servicio_catalogo.nombre",
        read_only=True
    )
    plan_detalle_estado = serializers.CharField(
        source="plan_detalle.estado",
        read_only=True
    )
    estado_display = serializers.SerializerMethodField()

    class Meta:
        model = CitaDetalle
        fields = [
            "id",
            "cita",
            "plan_detalle",
            "servicio_catalogo",
            "servicio_nombre",
            "estado",
            "estado_display",
            "plan_detalle_estado",
            "tiempo_estandar_min",
            "precio_referencial",
            "observaciones",
            "orden_visual",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "cita", "created_at", "updated_at"]
    
    def get_estado_display(self, obj):
        """Retorna descripciÃ³n legible del estado."""
        estado_map = dict(EstadoPlanServicioDetalle.choices)
        return estado_map.get(obj.estado, obj.estado)


class CitaDetalleCreacionSerializer(serializers.Serializer):
    """
    Serializer para crear detalles de cita.
    Uso: al crear/editar una cita, se envÃ­a una lista de IDs de plan_detalle.
    """
    plan_detalle_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        min_length=1,
        help_text="Lista de IDs de PlanServicioDetalle a incluir en la cita"
    )


class CitaListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar citas.
    Incluye informaciÃ³n esencial sin mucho detalle.
    """
    vehiculo_placa = serializers.CharField(
        source="vehiculo.placa",
        read_only=True
    )
    cliente_nombres = serializers.SerializerMethodField()
    servicios_count = serializers.SerializerMethodField()
    servicios_nombres = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Cita
        fields = [
            "id",
            "vehiculo",
            "vehiculo_placa",
            "cliente",
            "cliente_nombres",
            "estado",
            "estado_display",
            "fecha_hora_inicio_programada",
            "fecha_hora_fin_programada",
            "motivo_visita",
            "servicios_count",
            "servicios_nombres",
            "reprogramaciones_count",
            "created_at",
        ]
        read_only_fields = fields
    
    def get_cliente_nombres(self, obj):
        """Retorna nombre completo del cliente/propietario."""
        if obj.cliente:
            return obj.cliente.nombres
        elif obj.vehiculo and obj.vehiculo.propietario:
            return obj.vehiculo.propietario.nombres
        return "Cliente desconocido"
    
    def get_servicios_count(self, obj):
        """Retorna cantidad de servicios en esta cita."""
        return obj.detalles.count() if hasattr(obj, 'detalles') else 0
    
    def get_servicios_nombres(self, obj):
        """Retorna lista con nombres de servicios."""
        if hasattr(obj, 'detalles'):
            return [
                detalle.servicio_catalogo.nombre 
                for detalle in obj.detalles.all()
                if detalle.servicio_catalogo
            ]
        return []
    
    def get_estado_display(self, obj):
        """Retorna descripciÃ³n legible del estado."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoCita
        estado_map = dict(EstadoCita.choices)
        return estado_map.get(obj.estado, obj.estado)


class CitaDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para detalle completo de una cita.
    Incluye cabecera, servicios seleccionados (CitaDetalles) y espacios.
    """
    vehiculo = VehiculoListadoSerializer(read_only=True)
    cliente = UsuarioPropietarioSerializer(read_only=True)
    detalles = CitaDetalleIndividualSerializer(many=True, read_only=True)
    espacios_segmentos = CitaEspacioSegmentoSerializer(many=True, read_only=True)
    estado_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Cita
        fields = [
            "id",
            "vehiculo",
            "cliente",
            "estado",
            "estado_display",
            "fecha_hora_inicio_programada",
            "fecha_hora_fin_programada",
            "duracion_estimada_min",
            "motivo_visita",
            "observaciones_cliente",
            "reprogramaciones_count",
            "ultima_reprogramacion_at",
            "motivo_ultima_reprogramacion",
            "detalles",
            "espacios_segmentos",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
    
    def get_estado_display(self, obj):
        """Retorna descripciÃ³n legible del estado."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoCita
        estado_map = dict(EstadoCita.choices)
        return estado_map.get(obj.estado, obj.estado)


# ============================================================================
# HELPER PARA VALIDACIÃ“N DE CONFLICTOS DE ESPACIOS
# ============================================================================

def validar_conflictos_espacios_en_bd(segmentos_data, empresa_id, excluir_cita_id=None):
    """
    Valida que no haya conflictos de espacios contra citas activas en BD.
    
    Args:
        segmentos_data: lista de dicts con {espacio_trabajo_id, inicio_programado, fin_programado, ...}
        empresa_id: UUID de la empresa/tenant
        excluir_cita_id: UUID de cita a excluir (para ediciÃ³n/reprogramaciÃ³n)
    
    Raises:
        serializers.ValidationError: si hay conflictos
    
    Estados considerados "activos" que pueden ocupar agenda:
    - PROGRAMADA
    - EN_ESPERA_INGRESO
    - EN_PROCESO
    """
    from modulos.vehiculos_servicios_plan_citas.models import EstadoCita, CitaEspacioSegmento
    
    estados_activos = [
        EstadoCita.PROGRAMADA,
        EstadoCita.EN_ESPERA_INGRESO,
        EstadoCita.EN_PROCESO,
    ]
    
    for segmento in segmentos_data:
        espacio_id = segmento.get("espacio_trabajo_id")
        inicio_nuevo = segmento.get("inicio_programado")
        fin_nuevo = segmento.get("fin_programado")
        
        if not all([espacio_id, inicio_nuevo, fin_nuevo]):
            continue
        
        # Buscar segmentos activos del mismo espacio que se cruzan
        query = CitaEspacioSegmento.objects.filter(
            espacio_trabajo_id=espacio_id,
            cita__empresa_id=empresa_id,
            cita__estado__in=estados_activos
        )
        
        # Si es ediciÃ³n, excluir la propia cita
        if excluir_cita_id:
            query = query.exclude(cita_id=excluir_cita_id)
        
        conflictos = query.filter(
            inicio_programado__lt=fin_nuevo,
            fin_programado__gt=inicio_nuevo
        ).exists()
        
        if conflictos:
            raise serializers.ValidationError(
                {
                    "segmentos_espacio": 
                    f"Conflicto de agenda: ya existe cita activa en espacio {espacio_id} "
                    f"durante el rango {inicio_nuevo} - {fin_nuevo}."
                }
            )


class CitaCreacionSerializer(serializers.Serializer):
    """
    Serializer para crear una cita.
    
    IMPORTANTE - NUEVA ESTRATEGIA DE VALIDACIÃ“N:
    - El backend calcula segmentos canÃ³nicos usando el servicio de programaciÃ³n
    - El frontend PUEDE enviar segmentos_espacio, pero son INFORMATIVOS
    - El backend valida que coincidan exactamente con los canÃ³nicos
    - Si no coinciden, rechaza la solicitud con error claro
    - Esto asegura que backend es fuente de verdad para programaciÃ³n
    """
    vehiculo_id = serializers.UUIDField(write_only=True)
    cliente_id = serializers.UUIDField(required=False, allow_null=True, write_only=True)
    plan_servicio_id = serializers.UUIDField(write_only=True)
    servicios_plan_detalle_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1,
        write_only=True
    )
    canal_origen = serializers.CharField(max_length=20, write_only=True)
    fecha_hora_inicio_programada = serializers.DateTimeField(write_only=True)
    espacio_trabajo_id = serializers.UUIDField(
        help_text="Espacio en el que se programarÃ¡ la cita",
        write_only=True
    )
    duracion_estimada_min = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    motivo_visita = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    observaciones_cliente = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    segmentos_espacio = CitaEspacioSegmentoCreacionSerializer(
        many=True,
        required=False,
        help_text="OPCIONAL: Frontend puede enviar segmentos informativos. Backend los reemplaza con canÃ³nicos.",
        write_only=True
    )
    
    # Campos de lectura para la respuesta
    id = serializers.UUIDField(read_only=True)
    estado = serializers.SerializerMethodField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    
    def validate(self, data):
        """Validar datos de la cita y construir segmentos canÃ³nicos."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoCita, CanalOrigenCita
        from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService
        
        usuario = self.context.get("usuario_autenticado")
        empresa = self.context.get("empresa")
        
        # ========== VALIDACIÃ“N BÃSICA DE REFERENCIAS ==========
        
        try:
            vehiculo = Vehiculo.objects.get(id=data["vehiculo_id"], empresa=empresa)
        except Vehiculo.DoesNotExist:
            raise serializers.ValidationError({"vehiculo_id": "VehÃ­culo no encontrado."})
        
        if usuario.rol.nombre == "USUARIO":
            if vehiculo.propietario != usuario:
                raise serializers.ValidationError({"vehiculo_id": "No es tu vehÃ­culo."})
            data["cliente_id"] = usuario.id
        else:
            if not data.get("cliente_id"):
                raise serializers.ValidationError({"cliente_id": "Obligatorio para asesor."})
            try:
                cliente = Usuario.objects.get(id=data["cliente_id"], empresa=empresa)
            except Usuario.DoesNotExist:
                raise serializers.ValidationError({"cliente_id": "Cliente no encontrado."})
            
            if vehiculo.propietario_id != data["cliente_id"]:
                raise serializers.ValidationError(
                    {"cliente_id": "El cliente debe ser el propietario del vehÃ­culo."}
                )
        
        try:
            plan = PlanServicioVehiculo.objects.get(
                id=data["plan_servicio_id"],
                vehiculo=vehiculo,
                empresa=empresa
            )
        except PlanServicioVehiculo.DoesNotExist:
            raise serializers.ValidationError({"plan_servicio_id": "Plan no encontrado."})
        
        data["plan_servicio"] = plan
        data["vehiculo"] = vehiculo
        
        servicios_ids = data["servicios_plan_detalle_ids"]
        servicios = PlanServicioDetalle.objects.filter(
            id__in=servicios_ids,
            plan_servicio=plan,
            empresa=empresa
        )
        
        if servicios.count() != len(servicios_ids):
            raise serializers.ValidationError({"servicios_plan_detalle_ids": "Servicios invÃ¡lidos."})
        
        # Validar que ninguno estÃ¡ en otra cita activa
        citas_activas_con_servicios = CitaDetalle.objects.filter(
            plan_detalle_id__in=servicios_ids,
            cita__empresa=empresa,
            cita__estado__in=[EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
        ).exists()
        
        if citas_activas_con_servicios:
            raise serializers.ValidationError(
                {"servicios_plan_detalle_ids": "Algunos servicios ya estÃ¡n asignados a otras citas activas."}
            )
        
        if data["canal_origen"] not in dict(CanalOrigenCita.choices):
            raise serializers.ValidationError({"canal_origen": "Canal no vÃ¡lido."})
        
        # Validar espacio existe
        try:
            espacio = EspacioTrabajo.objects.get(id=data["espacio_trabajo_id"], empresa=empresa)
        except EspacioTrabajo.DoesNotExist:
            raise serializers.ValidationError({"espacio_trabajo_id": "Espacio no encontrado."})
        
        data["espacio"] = espacio
        
        # ========== VALIDACIÃ“N TEMPORAL ==========
        
        valido_temp, error_temp = CitasProgramacionService.validar_inicio_no_pasado(
            data["fecha_hora_inicio_programada"],
            empresa
        )
        if not valido_temp:
            raise serializers.ValidationError(
                {"fecha_hora_inicio_programada": error_temp}
            )

        # Inicio debe estar alineado a bloques de 30 minutos
        inicio = data["fecha_hora_inicio_programada"]
        inicio_minutos = inicio.hour * 60 + inicio.minute
        if not es_bloque_valido(inicio_minutos):
            raise serializers.ValidationError(
                {
                    "fecha_hora_inicio_programada": (
                        "La hora de inicio debe alinearse a bloques de 30 minutos."
                    )
                }
            )
        
        # ========== CÃLCULO DE DURACIÃ“N MÃNIMA ==========
        
        # Sumar tiempos estÃ¡ndar de todos los servicios
        duracion_minima = sum(
            s.tiempo_estandar_min
            for s in servicios
        )
        
        if duracion_minima <= 0:
            raise serializers.ValidationError(
                {
                    "servicios_plan_detalle_ids": 
                    "Los servicios seleccionados no tienen duraciÃ³n estÃ¡ndar definida."
                }
            )

        if duracion_minima % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                {
                    "servicios_plan_detalle_ids": (
                        "La duraciÃ³n total debe ser mÃºltiplo de 30 minutos."
                    )
                }
            )
        
        data["duracion_minima"] = duracion_minima
        data["duracion_estimada_min"] = data.get("duracion_estimada_min") or duracion_minima
        
        # ========== CONSTRUCCIÃ“N DE SEGMENTOS CANÃ“NICOS ==========
        
        hora_inicio_minutos = (
            data["fecha_hora_inicio_programada"].hour * 60 + 
            data["fecha_hora_inicio_programada"].minute
        )
        
        resultado_programacion = CitasProgramacionService.construir_reserva_canonica(
            espacio_id=str(espacio.id),
            fecha_inicio=data["fecha_hora_inicio_programada"],
            hora_inicio_solicitada=hora_inicio_minutos,
            duracion_requerida_min=duracion_minima,
            empresa=empresa,
        )
        
        if not resultado_programacion.valido:
            raise serializers.ValidationError(
                {
                    "segmentos_espacio": (
                        f"No se puede completar la reserva: {resultado_programacion.error}"
                    )
                }
            )
        
        # Guardar segmentos canÃ³nicos y estado de fragmentaciÃ³n
        data["segmentos_canonicos"] = resultado_programacion.segmentos
        data["fragmentado"] = resultado_programacion.fragmentado
        
        # ========== VALIDACIÃ“N DE INTEGRIDAD CONTRA BD ==========
        
        # Convertir segmentos canÃ³nicos a formato para validaciÃ³n
        segmentos_para_validar = [
            {
                "espacio_trabajo_id": str(espacio.id),
                "inicio_programado": seg["inicio_dt"],
                "fin_programado": seg["fin_dt"],
            }
            for seg in resultado_programacion.segmentos
        ]
        
        validar_conflictos_espacios_en_bd(
            segmentos_para_validar,
            empresa.id,
            excluir_cita_id=None
        )
        
        # ========== VALIDACIÃ“N DE SEGMENTOS ENVIADOS POR FRONTEND (INFORMATIVO) ==========
        
        # Si el frontend enviÃ³ segmentos, validarlos contra los canÃ³nicos (solo informativo)
        segmentos_frontend = data.get("segmentos_espacio", [])
        if segmentos_frontend:
            # Validar que al menos sean del mismo espacio
            for seg_fe in segmentos_frontend:
                if seg_fe.get("espacio_trabajo_id") != str(espacio.id):
                    raise serializers.ValidationError(
                        {
                            "segmentos_espacio":
                            "Los segmentos enviados pertenecen a espacios diferentes al principal."
                        }
                    )
        
        return data
    
    def get_estado(self, obj):
        """Retorna descripciÃ³n legible del estado."""
        from modulos.vehiculos_servicios_plan_citas.models import EstadoCita
        estado_map = dict(EstadoCita.choices)
        return estado_map.get(obj.estado, obj.estado)


class CitaEdicionSerializer(serializers.Serializer):
    """Serializer para editar/reprogramar una cita."""
    fecha_hora_inicio_programada = serializers.DateTimeField(required=False, write_only=True)
    fecha_hora_fin_programada = serializers.DateTimeField(required=False, write_only=True)
    motivo_visita = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    observaciones_cliente = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    segmentos_espacio = CitaEspacioSegmentoCreacionSerializer(many=True, required=False, write_only=True)
    motivo_reprogramacion = serializers.CharField(max_length=500, required=False, allow_blank=True, write_only=True)
    servicios_plan_detalle_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        min_length=1,
        help_text="Lista de IDs de PlanServicioDetalle a actualizar",
        write_only=True
    )
    
    def validate(self, data):
        """Validaciones de ediciÃ³n de cita."""
        # Si se especifican ambas fechas, validar que inicio < fin
        if "fecha_hora_inicio_programada" in data and "fecha_hora_fin_programada" in data:
            if data["fecha_hora_inicio_programada"] >= data["fecha_hora_fin_programada"]:
                raise serializers.ValidationError("Fecha de inicio debe ser anterior a fin.")
        
        # Si se especifican servicios_plan_detalle_ids, validar completamente
        if "servicios_plan_detalle_ids" in data:
            empresa = self.context.get("empresa")
            servicios_ids = data["servicios_plan_detalle_ids"]
            
            # Obtener instancia desde contexto para validaciÃ³n completa y validar que todos pertenecen al mismo plan
            instance = self.context.get("instance")
            
            if instance:
                # Validar que todos pertenecen al plan de la cita
                servicios = PlanServicioDetalle.objects.filter(
                    id__in=servicios_ids,
                    plan_servicio=instance.plan_servicio,
                    empresa=empresa
                )
                
                # Validar conteo exacto: enviados vs recuperados
                if servicios.count() != len(servicios_ids):
                    raise serializers.ValidationError(
                        {
                            "servicios_plan_detalle_ids": 
                            f"Se esperaban {len(servicios_ids)} servicios de este plan; "
                            f"solo {servicios.count()} existen o pertenecen al plan."
                        }
                    )
                
                # Validar no duplicados en payload
                if len(servicios_ids) != len(set(servicios_ids)):
                    raise serializers.ValidationError(
                        {"servicios_plan_detalle_ids": "Hay IDs duplicados en la lista."}
                    )
                
                # Validar que ninguno estÃ¡ en otra cita activa (excepto la actual)
                from modulos.vehiculos_servicios_plan_citas.models import EstadoCita
                citas_activas_conflictivas = CitaDetalle.objects.filter(
                    plan_detalle_id__in=servicios_ids,
                    cita__empresa=empresa,
                    cita__estado__in=[EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO, EstadoCita.EN_PROCESO]
                ).exclude(cita=instance).exists()
                
                if citas_activas_conflictivas:
                    raise serializers.ValidationError(
                        {"servicios_plan_detalle_ids": "Algunos servicios estÃ¡n asignados a otras citas activas."}
                    )
            else:
                # Sin instancia, solo validar existencia en empresa
                servicios = PlanServicioDetalle.objects.filter(
                    id__in=servicios_ids,
                    empresa=empresa
                )
                
                if servicios.count() != len(servicios_ids):
                    raise serializers.ValidationError(
                        {"servicios_plan_detalle_ids": "Algunos servicios no existen o no pertenecen a la empresa."}
                    )
        
        # ** Validar conflictos de espacios contra BD (excluyendo la cita siendo editada) **
        if "segmentos_espacio" in data:
            empresa = self.context.get("empresa")
            instance = self.context.get("instance")
            excluir_cita_id = instance.id if instance else None
            
            segmentos_espacio = data.get("segmentos_espacio", [])
            
            # ValidaciÃ³n interna (overlaps dentro del payload)
            espacios_usados = {}
            for segmento in segmentos_espacio:
                espacio_id = segmento.get("espacio_trabajo_id")
                inicio = segmento.get("inicio_programado")
                fin = segmento.get("fin_programado")
                
                # Validar que el espacio existe
                try:
                    EspacioTrabajo.objects.get(id=espacio_id, empresa=empresa)
                except EspacioTrabajo.DoesNotExist:
                    raise serializers.ValidationError(
                        {"segmentos_espacio": f"Espacio {espacio_id} no encontrado."}
                    )
                
                # Detectar overlaps internos
                if espacio_id not in espacios_usados:
                    espacios_usados[espacio_id] = []
                
                for tiempo_previo in espacios_usados[espacio_id]:
                    inicio_previo, fin_previo = tiempo_previo
                    if inicio < fin_previo and fin > inicio_previo:
                        raise serializers.ValidationError(
                            {"segmentos_espacio": f"Solapamiento interno en espacio {espacio_id}."}
                        )
                
                espacios_usados[espacio_id].append((inicio, fin))
            
            # ValidaciÃ³n contra BD
            validar_conflictos_espacios_en_bd(segmentos_espacio, empresa.id, excluir_cita_id=excluir_cita_id)
        
        return data


class CitaCancelacionSerializer(serializers.Serializer):
    """Serializer para cancelar una cita."""
    motivo_cancelacion = serializers.CharField(max_length=500, required=True, write_only=True)
    
    # Campos de lectura para la respuesta
    id = serializers.UUIDField(read_only=True)


# ============================================================================
# SERIALIZER PARA PREVIEW/VALIDACIÃ“N DE INTENCIÃ“N DE CITA (CU18 - Tentative)
# ============================================================================

class CitaPreviewIntencionSerializer(serializers.Serializer):
    """
    Serializer para validar tentativamente una intenciÃ³n de cita ANTES de crearla.
    
    Esta es una operaciÃ³n READ-ONLY (no persiste nada).
    
    Request (write_only):
    - vehiculo_id: UUID del vehÃ­culo
    - servicios_ids: Lista de UUIDs de PlanServicioDetalle
    - fecha_hora_inicio: Datetime de inicio solicitada
    - espacio_trabajo_id: (opcional) UUID del espacio preferido
    
    Response (read_only):
    - fecha_hora_inicio: Datetime initial (confirmaciÃ³n)
    - fecha_hora_fin_estimada: Datetime calculado por backend
    - es_valida: Boolean si la programaciÃ³n es posible
    - duracion_total_min: Minutos totales de servicios
    - fragmentado: Boolean si cita se fragmenta multi-dÃ­a
    - segmentos_preview: Lista de segmentos temporales calculados
    - mensajes: Lista de mensajes/advertencias
    
    IMPORTANTE:
    - No modifica BD
    - Usa CitasProgramacionService.construir_reserva_canonica
    - Respeta horarios operativos, ocupaciÃ³n, fragmentaciÃ³n
    - Si es_valida=False, el frontend deberÃ­a alertar al usuario
    """
    
    # ========== INPUT (write_only) ==========
    vehiculo_id = serializers.UUIDField(
        required=True,
        write_only=True,
        help_text="UUID del vehÃ­culo"
    )
    servicios_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        write_only=True,
        min_length=1,
        help_text="Lista de IDs de PlanServicioDetalle"
    )
    fecha_hora_inicio = serializers.DateTimeField(
        required=True,
        write_only=True,
        help_text="Fecha y hora de inicio solicitada"
    )
    espacio_trabajo_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        write_only=True,
        help_text="UUID del espacio de trabajo preferido (opcional)"
    )
    
    # ========== OUTPUT (read_only) ==========
    fecha_hora_inicio_respuesta = serializers.DateTimeField(
        read_only=True,
        help_text="Fecha y hora de inicio (confirmaciÃ³n)"
    )
    fecha_hora_fin_estimada = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Fecha y hora fin calculada por backend"
    )
    es_valida = serializers.BooleanField(
        read_only=True,
        help_text="Â¿Es posible programar la cita con esos parÃ¡metros"
    )
    duracion_total_min = serializers.IntegerField(
        read_only=True,
        help_text="Minutos totales de servicios"
    )
    fragmentado = serializers.BooleanField(
        read_only=True,
        help_text="Â¿La cita se fragmenta en varios dÃ­as"
    )
    segmentos_preview = serializers.ListField(
        read_only=True,
        help_text="Preview de segmentos calculados"
    )
    mensajes = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text="Mensajes/advertencias del servidor"
    )
    
    def validate_vehiculo_id(self, value):
        """Validar que el vehÃ­culo existe y pertenece a la empresa."""
        empresa = self.context.get("empresa")
        
        try:
            vehiculo = Vehiculo.objects.get(id=value, empresa=empresa)
        except Vehiculo.DoesNotExist:
            raise serializers.ValidationError(
                "El vehÃ­culo especificado no existe en esta empresa."
            )
        
        return vehiculo
    
    def validate_servicios_ids(self, value):
        """Validar que los servicios existen y pertenecen a la empresa."""
        empresa = self.context.get("empresa")
        
        if not value or len(value) == 0:
            raise serializers.ValidationError(
                "Debe proporcionar al menos un servicio."
            )
        
        # Buscar todos los servicios
        servicios = PlanServicioDetalle.objects.filter(
            id__in=value,
            empresa=empresa
        )
        
        if servicios.count() != len(value):
            raise serializers.ValidationError(
                f"Se esperaban {len(value)} servicios; solo {servicios.count()} existen en la empresa."
            )
        
        return servicios
    
    def validate_fecha_hora_inicio(self, value):
        """Validar que la fecha/hora es vÃ¡lida (no pasado)."""
        from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService
        
        empresa = self.context.get("empresa")
        
        # Validar que no sea pasado
        valido, error = CitasProgramacionService.validar_inicio_no_pasado(value, empresa)
        if not valido:
            raise serializers.ValidationError(error)

        inicio_minutos = value.hour * 60 + value.minute
        if not es_bloque_valido(inicio_minutos):
            raise serializers.ValidationError(
                "La hora de inicio debe alinearse a bloques de 30 minutos."
            )
        
        return value
    
    def validate_espacio_trabajo_id(self, value):
        """Validar que el espacio existe (si se proporciona)."""
        if value is None:
            return value
        
        empresa = self.context.get("empresa")
        
        try:
            espacio = EspacioTrabajo.objects.get(id=value, empresa=empresa)
        except EspacioTrabajo.DoesNotExist:
            raise serializers.ValidationError(
                "El espacio de trabajo especificado no existe en esta empresa."
            )
        
        return espacio
    
    def validate(self, data):
        """
        ValidaciÃ³n completa: calcular la reserva tentativa.
        
        LÃ³gica:
        1. Obtener servicios con sus duraciones
        2. Calcular duraciÃ³n total
        3. Llamar a CitasProgramacionService.construir_reserva_canonica()
        4. Guardar resultado en validated_data para uso en create()
        """
        import logging
        logger = logging.getLogger(__name__)
        
        vehiculo = data.get("vehiculo_id")
        servicios_queryset = data.get("servicios_ids")  # Ya validado
        fecha_hora_inicio = data.get("fecha_hora_inicio")
        espacio_trabajo = data.get("espacio_trabajo_id")
        empresa = self.context.get("empresa")
        
        # ðŸ” DEBUG: Log detallado de parÃ¡metros recibidos
        logger.warning(f"[CitaPreviewIntencion] ParÃ¡metros recibidos:")
        logger.warning(f"  - fecha_hora_inicio (raw): {fecha_hora_inicio} (type: {type(fecha_hora_inicio).__name__})")
        logger.warning(f"  - fecha_hora_inicio (ISO): {fecha_hora_inicio.isoformat() if fecha_hora_inicio else 'None'}")
        logger.warning(f"  - hora en minutos: {fecha_hora_inicio.hour * 60 + fecha_hora_inicio.minute if fecha_hora_inicio else 'N/A'}")
        logger.warning(f"  - espacio_trabajo: {espacio_trabajo.nombre if espacio_trabajo else 'Auto-asignar'}")
        logger.warning(f"  - servicios: {len(list(servicios_queryset))} servicios")
        logger.warning(f"  - empresa: {empresa.nombre if empresa else 'None'}")
        
        # Calcular duraciÃ³n total de los servicios
        duracion_total_min = sum(
            s.tiempo_estandar_min for s in servicios_queryset
        )
        
        if duracion_total_min <= 0:
            raise serializers.ValidationError(
                "La duraciÃ³n total de los servicios debe ser mayor que 0 minutos."
            )
        if duracion_total_min % BLOQUE_MINUTOS != 0:
            raise serializers.ValidationError(
                "La duraciÃ³n total debe ser mÃºltiplo de 30 minutos."
            )
        
        # Usar CitasProgramacionService para calcular tentativamente
        from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService
        
        # Si no hay espacio preferido, usar el primero disponible con horarios
        if not espacio_trabajo:
            # Buscar espacios activos con horarios operativos
            espacios_con_horarios = EspacioTrabajo.objects.filter(
                empresa=empresa,
                activo=True
            ).exclude(horarios__isnull=True).distinct()
            
            if not espacios_con_horarios.exists():
                raise serializers.ValidationError(
                    "No hay espacios de trabajo disponibles con horarios operativos."
                )
            
            espacio_trabajo = espacios_con_horarios.first()
            logger.warning(f"  [AUTO] Espacio seleccionado: {espacio_trabajo.nombre}")
        
        # Convertir fecha_hora_inicio a hora en minutos desde medianoche
        hora_inicio_min = fecha_hora_inicio.hour * 60 + fecha_hora_inicio.minute
        
        logger.warning(f"[construir_reserva_canonica] Llamando con:")
        logger.warning(f"  - espacio_id: {espacio_trabajo.id}")
        logger.warning(f"  - fecha_inicio: {fecha_hora_inicio.date()}")
        logger.warning(f"  - hora_inicio_solicitada (min): {hora_inicio_min}")
        logger.warning(f"  - duracion_requerida_min: {duracion_total_min}")
        
        # Llamar al servicio de programaciÃ³n
        resultado = CitasProgramacionService.construir_reserva_canonica(
            espacio_id=str(espacio_trabajo.id),
            fecha_inicio=fecha_hora_inicio,
            hora_inicio_solicitada=hora_inicio_min,
            duracion_requerida_min=duracion_total_min,
            empresa=empresa,
            horizonte_dias=30,  # Buscar hasta 30 dÃ­as adelante
        )
        
        # Preparar respuesta
        mensajes = []
        
        if resultado.valido:
            mensajes.append("âœ“ La cita se puede programar correctamente.")
            if resultado.fragmentado:
                mensajes.append(
                    f"âš  La cita serÃ¡ fragmentada en {len(resultado.segmentos)} segmento(s) "
                    f"debido a limitaciones de horarios."
                )
        else:
            mensajes.append(f"âœ— Error de programaciÃ³n: {resultado.error}")
            if resultado.segmentos:
                mensajes.append(
                    f"Se pudieron programar {resultado.duracion_total_min} de "
                    f"{duracion_total_min} minutos solicitados."
                )
        
        # Calcular hora fin desde segmentos
        fecha_hora_fin = None
        if resultado.segmentos:
            ultimo_segmento = resultado.segmentos[-1]
            fecha_hora_fin = ultimo_segmento["fin_dt"]
        
        # Armar segmentos para preview
        segmentos_preview = []
        for i, seg in enumerate(resultado.segmentos, 1):
            segmentos_preview.append({
                "numero": i,
                "espacio_id": str(espacio_trabajo.id),
                "espacio": espacio_trabajo.nombre,
                "inicio": seg["inicio_dt"].isoformat(),
                "fin": seg["fin_dt"].isoformat(),
                "duracion_min": seg["duracion_min"],
            })
        
        # Guardar en contexto para usar en create()
        data["_resultado_programacion"] = resultado
        data["_fecha_hora_fin"] = fecha_hora_fin
        data["_duracion_total_min"] = duracion_total_min
        data["_fragmentado"] = resultado.fragmentado
        data["_segmentos_preview"] = segmentos_preview
        data["_mensajes"] = mensajes
        data["_es_valida"] = resultado.valido
        data["_espacio_trabajo_id"] = str(espacio_trabajo.id)
        data["_espacio_trabajo_nombre"] = espacio_trabajo.nombre
        
        return data
    
    def create(self, validated_data):
        """
        En realidad no creamos nada (NO persiste).
        Solo retornamos datos calculados en validate().
        """
        # Extraer datos calculados
        fecha_hora_inicio = validated_data.get("fecha_hora_inicio")
        fecha_hora_fin = validated_data.get("_fecha_hora_fin")
        es_valida = validated_data.get("_es_valida", False)
        duracion_total_min = validated_data.get("_duracion_total_min", 0)
        fragmentado = validated_data.get("_fragmentado", False)
        segmentos_preview = validated_data.get("_segmentos_preview", [])
        mensajes = validated_data.get("_mensajes", [])
        espacio_trabajo_id = validated_data.get("_espacio_trabajo_id")
        espacio_trabajo_nombre = validated_data.get("_espacio_trabajo_nombre")
        
        # Retornar dict para serializaciÃ³n
        return {
            "fecha_hora_inicio_respuesta": fecha_hora_inicio,
            "fecha_hora_fin_estimada": fecha_hora_fin,
            "es_valida": es_valida,
            "duracion_total_min": duracion_total_min,
            "fragmentado": fragmentado,
            "segmentos_preview": segmentos_preview,
            "mensajes": mensajes,
            "espacio_trabajo_id": espacio_trabajo_id,
            "espacio_trabajo_nombre": espacio_trabajo_nombre,
        }


# ============================================================================
# SERIALIZERS ESPECÃFICOS PARA CU21 - RECEPCIÃ“N MÃNIMA
# ============================================================================

class CitaRecepcionOperativaListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar citas en bandeja operativa de recepciÃ³n.
    
    Incluye:
    - Datos bÃ¡sicos de cita
    - InformaciÃ³n del vehÃ­culo y cliente
    - Estado y timestamps operativos
    - Contador de servicios
    - Flags de acciones permitidas
    """
    vehiculo_placa = serializers.CharField(
        source="vehiculo.placa",
        read_only=True,
        help_text="Placa del vehÃ­culo"
    )
    cliente_nombres = serializers.CharField(
        source="cliente.nombres",
        read_only=True,
        help_text="Nombres del cliente"
    )
    asesor_nombres = serializers.CharField(
        source="asesor_responsable.nombres",
        read_only=True,
        allow_null=True,
        help_text="Nombres del asesor responsable"
    )
    servicios_count = serializers.SerializerMethodField()
    acciones_flags = serializers.SerializerMethodField()

    class Meta:
        model = Cita
        fields = [
            "id",
            "vehiculo_placa",
            "cliente_nombres",
            "asesor_nombres",
            "estado",
            "fecha_hora_inicio_programada",
            "llegada_real_at",
            "finalizada_at",
            "vehiculo_devuelto_at",
            "servicios_count",
            "acciones_flags",
            "created_at",
        ]
        read_only_fields = fields

    def get_servicios_count(self, obj):
        """Contar servicios en la cita."""
        return obj.detalles.count()

    def get_acciones_flags(self, obj):
        """Retornar flags de acciones permitidas."""
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        return CitasRecepcionService.construir_flags_acciones(obj)


class CitaRecepcionOperativaDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para ver detalle de cita en contexto de recepciÃ³n.
    
    Incluye:
    - Datos completos de la cita
    - Lista de servicios/detalles
    - Espacios y segmentos
    - InformaciÃ³n del vehÃ­culo
    - Acciones permitidas
    """
    vehiculo = VehiculoSerializer(read_only=True)
    cliente = serializers.SerializerMethodField()
    asesor_responsable = serializers.SerializerMethodField()
    detalles = serializers.SerializerMethodField()
    espacios_segmentos = CitaEspacioSegmentoSerializer(many=True, read_only=True)
    acciones_flags = serializers.SerializerMethodField()

    class Meta:
        model = Cita
        fields = [
            "id",
            "vehiculo",
            "cliente",
            "asesor_responsable",
            "estado",
            "fecha_hora_inicio_programada",
            "fecha_hora_fin_programada",
            "duracion_estimada_min",
            "llegada_real_at",
            "finalizada_at",
            "vehiculo_devuelto_at",
            "motivo_visita",
            "observaciones_cliente",
            "detalles",
            "espacios_segmentos",
            "acciones_flags",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_cliente(self, obj):
        """Serializar cliente de forma simplificada."""
        if obj.cliente:
            return {
                "id": str(obj.cliente.id),
                "nombres": obj.cliente.nombres,
                "email": obj.cliente.email,
                "telefono": obj.cliente.telefono,
            }
        return None

    def get_asesor_responsable(self, obj):
        """Serializar asesor de forma simplificada."""
        if obj.asesor_responsable:
            return {
                "id": str(obj.asesor_responsable.id),
                "nombres": obj.asesor_responsable.nombres,
                "email": obj.asesor_responsable.email,
            }
        return None

    def get_detalles(self, obj):
        """Retornar detalles de servicios con info completa."""
        detalles = obj.detalles.all()
        return [
            {
                "id": str(d.id),
                "servicio_nombre": d.servicio_catalogo.nombre if d.servicio_catalogo else "N/A",
                "tiempo_estandar_min": d.tiempo_estandar_min,
                "precio_referencial": str(d.precio_referencial),
                "estado": d.estado,
            }
            for d in detalles
        ]

    def get_acciones_flags(self, obj):
        """Retornar flags de acciones permitidas."""
        from modulos.atencion_tecnica_ejecucion.services.citas_recepcion_service import CitasRecepcionService
        return CitasRecepcionService.construir_flags_acciones(obj)


class RegistrarLlegadaSerializer(serializers.Serializer):
    """
    Serializer para registrar llegada del vehÃ­culo.
    
    Campos:
    - llegada_real_at: DateTimeField opcional (si no viene, usar timezone.now())
    """
    llegada_real_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Fecha y hora de llegada (opcional, default: ahora)"
    )


class AjustarServiciosRecepcionSerializer(serializers.Serializer):
    """
    Serializer para ajustar servicios antes de iniciar trabajo.
    
    Campos:
    - servicios_plan_detalle_ids: Lista de UUIDs de servicios
    - motivo_visita: Resumen del motivo (opcional)
    - observaciones_cliente: Observaciones (opcional)
    """
    servicios_plan_detalle_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True,
        min_length=1,
        help_text="IDs de PlanServicioDetalle a incluir en la cita"
    )
    motivo_visita = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Resumen del motivo de la visita"
    )
    observaciones_cliente = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=500,
        help_text="Observaciones adicionales del cliente"
    )


class MarcarEnProcesoSerializer(serializers.Serializer):
    """
    Serializer para marcar cita como EN_PROCESO (inicio de trabajo).
    
    Campos:
    - llegada_real_at: DateTimeField opcional (si no existe, guardarla)
    """
    llegada_real_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Fecha y hora de llegada (opcional, default: ahora)"
    )


class MarcarVehiculoDevueltoSerializer(serializers.Serializer):
    """
    Serializer para marcar vehÃ­culo como devuelto/recolectado.
    
    Campos:
    - vehiculo_devuelto_at: DateTimeField opcional (si no viene, usar timezone.now())
    """
    vehiculo_devuelto_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="Fecha y hora de devoluciÃ³n (opcional, default: ahora)"
    )
