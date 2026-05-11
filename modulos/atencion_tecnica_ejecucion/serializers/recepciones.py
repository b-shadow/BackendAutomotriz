"""
Serializers para RecepciÃ³n de VehÃ­culos.

Flujo de recepciÃ³n:
1. Asesor selecciona cita PROGRAMADA
2. Registra recepciÃ³n (km, combustible, condiciÃ³n)
3. Backend cambia Cita.estado = EN_PROCESO
4. Permite luego generar Orden de Trabajo
"""

from rest_framework import serializers
from django.utils import timezone
from django.db import transaction
from modulos.atencion_tecnica_ejecucion.models import RecepcionVehiculo, NivelCombustible
from modulos.atencion_tecnica_ejecucion.models import (
    PresupuestoCita,
    PresupuestoDetalle,
    EstadoPresupuestoCita,
    EstadoPresupuestoDetalle,
    AvanceVehiculo,
    TipoAvanceVehiculo,
)
from modulos.vehiculos_servicios_plan_citas.models import Cita, EstadoCita, CitaEspacioSegmento
from modulos.administracion_acceso_configuracion.models import Usuario, Empresa
from modulos.vehiculos_servicios_plan_citas.services.citas_programacion_service import CitasProgramacionService
from modulos.vehiculos_servicios_plan_citas.services.bloques_tiempo import BLOQUE_MINUTOS
from modulos.atencion_tecnica_ejecucion.services.ordenes_trabajo import OrdenTrabajoService


class RecepcionVehiculoSerializer(serializers.ModelSerializer):
    """
    Serializer base para RecepcionVehiculo.
    Lectura/escritura de datos de recepciÃ³n.
    """
    # InformaciÃ³n relacionada (read-only)
    cita_numero = serializers.SerializerMethodField()
    vehiculo_placa = serializers.SerializerMethodField()
    vehiculo_marca_modelo = serializers.SerializerMethodField()
    cliente_nombre = serializers.SerializerMethodField()
    asesor_nombre = serializers.CharField(
        source="asesor_registra.nombres",
        read_only=True
    )
    recogido_por_nombre = serializers.CharField(source="recogido_por.nombres", read_only=True)

    class Meta:
        model = RecepcionVehiculo
        fields = [
            "id",
            "empresa",
            "cita",
            "cita_numero",
            "vehiculo_placa",
            "vehiculo_marca_modelo",
            "cliente_nombre",
            "asesor_registra",
            "asesor_nombre",
            "fecha_recepcion",
            "kilometraje_ingreso",
            "nivel_combustible",
            "observaciones",
            "fecha_recogida",
            "recogido_por",
            "recogido_por_nombre",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "empresa",
            "asesor_registra",
            "fecha_recepcion",
            "created_at",
            "updated_at",
        ]

    def get_cita_numero(self, obj):
        """Retorna ID de la cita (identificador)."""
        return str(obj.cita.id)

    def get_vehiculo_placa(self, obj):
        """Retorna placa del vehÃ­culo."""
        if obj.cita.vehiculo:
            return obj.cita.vehiculo.placa
        return None

    def get_vehiculo_marca_modelo(self, obj):
        """Retorna marca y modelo del vehÃ­culo."""
        if obj.cita.vehiculo:
            return f"{obj.cita.vehiculo.marca} {obj.cita.vehiculo.modelo}"
        return None

    def get_cliente_nombre(self, obj):
        """Retorna nombre del cliente (propietario del vehÃ­culo)."""
        if obj.cita.vehiculo and obj.cita.vehiculo.propietario:
            return obj.cita.vehiculo.propietario.nombres
        return None


class RecepcionVehiculoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear RecepcionVehiculo.
    Valida:
    - Cita existe y estÃ¡ PROGRAMADA/EN_ESPERA_INGRESO
    - Campos requeridos completos
    - Cambia estado de cita a EN_PROCESO
    """
    cita_id = serializers.UUIDField(write_only=True)

    class Meta:
        model = RecepcionVehiculo
        fields = [
            "cita_id",
            "kilometraje_ingreso",
            "nivel_combustible",
            "observaciones",
        ]

    def validate_cita_id(self, value):
        """Valida que cita existe, estÃ¡ PROGRAMADA/EN_ESPERA_INGRESO y usuario tiene permiso."""
        request = self.context.get("request")
        empresa_id = self.context.get("empresa_id")

        try:
            cita = Cita.objects.get(id=value, empresa_id=empresa_id)
        except Cita.DoesNotExist:
            raise serializers.ValidationError(
                f"Cita {value} no encontrada en esta empresa."
            )

        # Validar estado de cita
        if cita.estado not in [EstadoCita.PROGRAMADA, EstadoCita.EN_ESPERA_INGRESO]:
            raise serializers.ValidationError(
                f"La cita debe estar en estado PROGRAMADA o EN_ESPERA_INGRESO. "
                f"Estado actual: {cita.get_estado_display()}"
            )

        # Validar que no exista ya una recepciÃ³n
        if hasattr(cita, "recepcion"):
            raise serializers.ValidationError(
                "Esta cita ya tiene una recepciÃ³n registrada."
            )

        return value

    def validate_kilometraje_ingreso(self, value):
        """Valida que kilometraje sea positivo."""
        if value < 0:
            raise serializers.ValidationError(
                "El kilometraje debe ser un valor positivo."
            )
        return value

    def _normalizar_duracion_a_bloques(self, duracion_min):
        if duracion_min <= 0:
            return 0
        residuo = duracion_min % BLOQUE_MINUTOS
        if residuo == 0:
            return duracion_min
        return duracion_min + (BLOQUE_MINUTOS - residuo)

    def _recalcular_programacion_desde_llegada(self, cita, empresa_id, llegada_real_at):
        primer_segmento = cita.espacios_segmentos.order_by("orden_segmento").first()
        if not primer_segmento or not primer_segmento.espacio_trabajo_id:
            return

        duracion_servicios = sum((d.tiempo_estandar_min or 0) for d in cita.detalles.all())
        duracion_requerida = duracion_servicios if duracion_servicios > 0 else (cita.duracion_estimada_min or 0)
        duracion_requerida = self._normalizar_duracion_a_bloques(duracion_requerida)
        if duracion_requerida <= 0:
            return

        resultado = CitasProgramacionService.encontrar_primer_inicio_disponible(
            espacio_id=str(primer_segmento.espacio_trabajo_id),
            fecha_hora_inicio=llegada_real_at,
            duracion_requerida_min=duracion_requerida,
            empresa=cita.empresa,
        )
        if not resultado:
            raise serializers.ValidationError(
                "No se encontro disponibilidad para recalcular la cita desde la hora de llegada."
            )

        for segmento in cita.espacios_segmentos.all():
            segmento.delete()

        for orden, seg in enumerate(resultado["segmentos"], 1):
            CitaEspacioSegmento.objects.create(
                empresa_id=empresa_id,
                cita=cita,
                espacio_trabajo=primer_segmento.espacio_trabajo,
                orden_segmento=orden,
                tipo_segmento=getattr(primer_segmento, "tipo_segmento", "TALLER") or "TALLER",
                inicio_programado=seg["inicio_dt"],
                fin_programado=seg["fin_dt"],
                motivo="Recalculado automaticamente al registrar recepcion",
            )

        cita.fecha_hora_inicio_programada = resultado["inicio_dt"]
        cita.fecha_hora_fin_programada = resultado["fin_dt"]
        cita.duracion_estimada_min = duracion_requerida

    @transaction.atomic
    def create(self, validated_data):
        """
        Crea RecepcionVehiculo y cambia estado de cita a EN_PROCESO.
        """
        request = self.context.get("request")
        empresa_id = self.context.get("empresa_id")
        cita_id = validated_data.pop("cita_id")

        # Obtener cita nuevamente (validada)
        cita = Cita.objects.get(id=cita_id, empresa_id=empresa_id)

        llegada_real = timezone.now()

        self._recalcular_programacion_desde_llegada(
            cita=cita,
            empresa_id=empresa_id,
            llegada_real_at=llegada_real,
        )

        # Crear recepciÃ³n
        recepcion = RecepcionVehiculo.objects.create(
            empresa_id=empresa_id,
            cita=cita,
            asesor_registra=request.user,
            **validated_data
        )

        # Cambiar estado de cita a EN_PROCESO
        cita.estado = EstadoCita.EN_PROCESO
        cita.llegada_real_at = llegada_real
        cita.save(update_fields=[
            "estado",
            "llegada_real_at",
            "fecha_hora_inicio_programada",
            "fecha_hora_fin_programada",
            "duracion_estimada_min",
            "updated_at",
        ])

        # CU-23: al recepcionar, generar OT automaticamente en estado ABIERTA.
        try:
            OrdenTrabajoService.crear_orden_automatica(
                empresa=cita.empresa,
                cita=cita,
                asesor_responsable=request.user,
                observaciones="OT generada automaticamente al registrar recepcion.",
            )
        except ValueError as exc:
            raise serializers.ValidationError(
                {"detalle": f"No se pudo registrar la recepción: {str(exc)}"}
            ) from exc

        # CU-22: al recepcionar, generar presupuesto BORRADOR automaticamente si no existe.
        if not hasattr(cita, "presupuesto"):
            presupuesto = PresupuestoCita.objects.create(
                empresa=cita.empresa,
                cita=cita,
                estado=EstadoPresupuestoCita.BORRADOR,
                subtotal=0,
                descuento=0,
                total=0,
                observaciones="Presupuesto generado automáticamente al registrar recepción.",
            )
            subtotal = 0
            for cdet in cita.detalles.all().order_by("orden_visual", "created_at"):
                precio = cdet.precio_referencial or 0
                PresupuestoDetalle.objects.create(
                    empresa=cita.empresa,
                    presupuesto=presupuesto,
                    servicio_catalogo=cdet.servicio_catalogo,
                    descripcion=(cdet.servicio_catalogo.nombre if cdet.servicio_catalogo else "Servicio"),
                    cantidad=1,
                    tiempo_estandar_min=cdet.tiempo_estandar_min or 0,
                    precio_unitario=precio,
                    subtotal=precio,
                    estado=EstadoPresupuestoDetalle.ACTIVO,
                )
                subtotal += precio
            presupuesto.subtotal = subtotal
            presupuesto.total = subtotal
            presupuesto.save(update_fields=["subtotal", "total", "updated_at"])

        # Publicar avance base para vista cliente/admin (sin depender de publicación manual).
        AvanceVehiculo.objects.create(
            empresa=cita.empresa,
            cita=cita,
            orden_detalle=None,
            registrado_por=request.user,
            tipo=TipoAvanceVehiculo.GENERAL,
            estado_nuevo="EN TALLER",
            mensaje="Vehiculo recepcionado, en espera de inicio de trabajos.",
            porcentaje_avance=0,
            visible_cliente=True,
        )

        return recepcion


class RecepcionVehiculoDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer detallado para RecepcionVehiculo.
    Incluye informaciÃ³n completa de cita, vehÃ­culo y cliente.
    """
    # InformaciÃ³n de cita
    cita_numero = serializers.SerializerMethodField()
    cita_fecha_programada = serializers.SerializerMethodField()
    cita_estado = serializers.SerializerMethodField()

    # InformaciÃ³n de vehÃ­culo
    vehiculo_placa = serializers.SerializerMethodField()
    vehiculo_marca = serializers.SerializerMethodField()
    vehiculo_modelo = serializers.SerializerMethodField()
    vehiculo_ano = serializers.SerializerMethodField()

    # InformaciÃ³n de cliente
    cliente_nombre = serializers.SerializerMethodField()
    cliente_email = serializers.SerializerMethodField()
    cliente_telefono = serializers.SerializerMethodField()

    # InformaciÃ³n de asesor
    asesor_nombre = serializers.CharField(
        source="asesor_registra.nombres",
        read_only=True
    )
    asesor_email = serializers.CharField(
        source="asesor_registra.email",
        read_only=True
    )
    recogido_por_nombre = serializers.CharField(source="recogido_por.nombres", read_only=True)

    class Meta:
        model = RecepcionVehiculo
        fields = [
            "id",
            # Cita
            "cita_numero",
            "cita_fecha_programada",
            "cita_estado",
            # VehÃ­culo
            "vehiculo_placa",
            "vehiculo_marca",
            "vehiculo_modelo",
            "vehiculo_ano",
            # Cliente
            "cliente_nombre",
            "cliente_email",
            "cliente_telefono",
            # RecepciÃ³n
            "fecha_recepcion",
            "kilometraje_ingreso",
            "nivel_combustible",
            "condicion_general",
            "observaciones",
            "fecha_recogida",
            "recogido_por_nombre",
            # Asesor
            "asesor_nombre",
            "asesor_email",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_cita_numero(self, obj):
        return str(obj.cita.id)

    def get_cita_fecha_programada(self, obj):
        return obj.cita.fecha_hora_inicio

    def get_cita_estado(self, obj):
        return obj.cita.get_estado_display()

    def get_vehiculo_placa(self, obj):
        return obj.cita.vehiculo.placa if obj.cita.vehiculo else None

    def get_vehiculo_marca(self, obj):
        return obj.cita.vehiculo.marca if obj.cita.vehiculo else None

    def get_vehiculo_modelo(self, obj):
        return obj.cita.vehiculo.modelo if obj.cita.vehiculo else None

    def get_vehiculo_ano(self, obj):
        return obj.cita.vehiculo.anio if obj.cita.vehiculo else None

    def get_cliente_nombre(self, obj):
        if obj.cita.vehiculo and obj.cita.vehiculo.propietario:
            return obj.cita.vehiculo.propietario.nombres
        return None

    def get_cliente_email(self, obj):
        if obj.cita.vehiculo and obj.cita.vehiculo.propietario:
            return obj.cita.vehiculo.propietario.email
        return None

    def get_cliente_telefono(self, obj):
        if obj.cita.vehiculo and obj.cita.vehiculo.propietario:
            return obj.cita.vehiculo.propietario.telefono
        return None


class RecepcionVehiculoListaSerializer(serializers.ModelSerializer):
    """
    Serializer para listar recepciones (vista de tabla).
    InformaciÃ³n compacta y relevante.
    """
    # Cita
    cita_id = serializers.CharField(source="cita.id", read_only=True)

    # VehÃ­culo
    vehiculo_placa = serializers.CharField(
        source="cita.vehiculo.placa",
        read_only=True
    )

    # Cliente
    cliente_nombre = serializers.SerializerMethodField()

    # Asesor
    asesor_nombre = serializers.CharField(
        source="asesor_registra.nombres",
        read_only=True
    )
    recogido = serializers.SerializerMethodField()
    recogido_por_nombre = serializers.CharField(source="recogido_por.nombres", read_only=True)

    class Meta:
        model = RecepcionVehiculo
        fields = [
            "id",
            "cita_id",
            "vehiculo_placa",
            "cliente_nombre",
            "fecha_recepcion",
            "kilometraje_ingreso",
            "nivel_combustible",
            "asesor_nombre",
            "fecha_recogida",
            "recogido",
            "recogido_por_nombre",
        ]
        read_only_fields = fields

    def get_cliente_nombre(self, obj):
        if obj.cita.vehiculo and obj.cita.vehiculo.propietario:
            return obj.cita.vehiculo.propietario.nombres
        return None

    def get_recogido(self, obj):
        return bool(obj.fecha_recogida)


class RecepcionVehiculoActualizacionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar RecepcionVehiculo.
    Solo permite editar: condicion_general, observaciones
    (No permite editar km ni combustible despuÃ©s de registrado)
    """

    class Meta:
        model = RecepcionVehiculo
        fields = [
            "condicion_general",
            "observaciones",
        ]

    def update(self, instance, validated_data):
        """Actualiza solo campos permitidos."""
        if "condicion_general" in validated_data:
            instance.condicion_general = validated_data["condicion_general"]
        if "observaciones" in validated_data:
            instance.observaciones = validated_data["observaciones"]
        instance.save()
        return instance

