"""Serializers para Espacios de Trabajo y Horarios."""

from rest_framework import serializers
from app.models import (
    HorarioEspacioTrabajo,
    EspacioTrabajo,
)


# ============================================================================
# SERIALIZERS - ESPACIOS Y HORARIOS
# ============================================================================

class HorarioEspacioTrabajoSerializer(serializers.ModelSerializer):
    """Serializer base para Horario de Espacio de Trabajo."""
    dia_semana_display = serializers.SerializerMethodField()

    class Meta:
        model = HorarioEspacioTrabajo
        fields = [
            "id",
            "empresa",
            "espacio_trabajo",
            "dia_semana",
            "dia_semana_display",
            "hora_inicio",
            "hora_fin",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_dia_semana_display(self, obj):
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return dias[obj.dia_semana]


class EspacioTrabajoSerializer(serializers.ModelSerializer):
    """Serializer base para Espacio de Trabajo."""
    horarios = HorarioEspacioTrabajoSerializer(many=True, read_only=True)

    class Meta:
        model = EspacioTrabajo
        fields = [
            "id",
            "empresa",
            "codigo",
            "nombre",
            "tipo",
            "estado",
            "activo",
            "observaciones",
            "horarios",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ============================================================================
# SERIALIZERS ESPECÍFICOS PARA CU16 - CONFIGURAR ESPACIOS DE TRABAJO
# ============================================================================

def _validar_solapamiento_horario(espacio_trabajo, dia_semana, hora_inicio, hora_fin, horario_id_excluir=None):
    """
    Función auxiliar para validar solapamiento de horarios.
    
    IMPORTANTE: Valida que no existan DOS HORARIOS ACTIVOS solapados 
    del mismo espacio y día.
    
    Lógica de solapamiento:
    - Dos rangos de tiempo se solapan si: hora_inicio < otra.hora_fin AND hora_fin > otra.hora_inicio
    - Ejemplo 1 (NO solapan): 08:00-12:00 y 12:00-16:00 (son contiguos, no hay solapamiento)
    - Ejemplo 2 (SÍ solapan): 08:00-13:00 y 12:00-16:00 (13:00 > 12:00 y 08:00 < 16:00)
    
    Args:
        espacio_trabajo: Instancia de EspacioTrabajo
        dia_semana: Número de día (0-6, Lunes-Domingo)
        hora_inicio: time object de hora inicio
        hora_fin: time object de hora fin
        horario_id_excluir: ID del horario actual (si se está editando/reactivando), 
                            para excluirlo de la búsqueda
    
    Returns:
        tuple: (hay_conflicto: bool, horario_conflictivo: HorarioEspacioTrabajo or None)
            - hay_conflicto: True si existe otro horario activo solapado, False si no hay conflicto
            - horario_conflictivo: La instancia del horario que causa el conflicto (o None si no hay)
    """
    # Búsqueda: SOLO horarios ACTIVOS del mismo espacio y día
    horarios_activos = HorarioEspacioTrabajo.objects.filter(
        espacio_trabajo=espacio_trabajo,
        dia_semana=dia_semana,
        activo=True  # ← SOLO ACTIVOS
    )
    
    # Excluir el horario siendo editado/reactivado (si aplica)
    if horario_id_excluir:
        horarios_activos = horarios_activos.exclude(id=horario_id_excluir)
    
    # Buscar conflicto con solapamiento
    for horario in horarios_activos:
        # Verificar solapamiento: hora_inicio < otra.hora_fin AND hora_fin > otra.hora_inicio
        if hora_inicio < horario.hora_fin and hora_fin > horario.hora_inicio:
            return True, horario  # Hay conflicto
    
    return False, None  # Sin conflicto


class HorarioEspacioTrabajoListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar horarios de espacios de trabajo.
    Incluye día de semana en formato legible.
    """
    dia_semana_display = serializers.SerializerMethodField()
    
    class Meta:
        model = HorarioEspacioTrabajo
        fields = [
            "id",
            "dia_semana",
            "dia_semana_display",
            "hora_inicio",
            "hora_fin",
            "activo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    
    def get_dia_semana_display(self, obj):
        """Retorna nombre del día de la semana."""
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        return dias[obj.dia_semana]


class HorarioEspacioTrabajoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un horario de espacio de trabajo.
    
    Validaciones:
    - dia_semana válido (0-6)
    - hora_inicio < hora_fin
    - NO solapamiento con otros horarios activos del mismo espacio/día
    """
    
    class Meta:
        model = HorarioEspacioTrabajo
        fields = [
            "dia_semana",
            "hora_inicio",
            "hora_fin",
        ]
    
    def validate_dia_semana(self, value):
        """Validar que el día sea válido (0-6)."""
        if value < 0 or value > 6:
            raise serializers.ValidationError(
                "El día de la semana debe estar entre 0 (Lunes) y 6 (Domingo)."
            )
        return value
    
    def validate(self, data):
        """
        Validar que hora_inicio < hora_fin y que no haya solapamiento
        con otros horarios activos del mismo espacio y día.
        
        Un nuevo horario se crea ACTIVO por defecto, por lo que se valida
        contra todos los horarios activos del mismo espacio y día.
        """
        hora_inicio = data.get("hora_inicio")
        hora_fin = data.get("hora_fin")
        dia_semana = data.get("dia_semana")
        
        # Validar rango de horas
        if hora_inicio and hora_fin and hora_inicio >= hora_fin:
            raise serializers.ValidationError(
                {"hora_fin": "La hora de fin debe ser mayor que la hora de inicio."}
            )
        
        # Validar solapamiento con otros horarios activos del mismo espacio
        if dia_semana is not None and hora_inicio and hora_fin:
            espacio_trabajo = self.context.get("espacio_trabajo")
            if espacio_trabajo:
                hay_conflicto, horario_conflictivo = _validar_solapamiento_horario(
                    espacio_trabajo=espacio_trabajo,
                    dia_semana=dia_semana,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                    horario_id_excluir=None  # Es creación, no hay ID
                )
                
                if hay_conflicto:
                    raise serializers.ValidationError(
                        {
                            "hora_inicio": (
                                f"Ya existe un horario activo que se solapa con el rango indicado: "
                                f"{horario_conflictivo.hora_inicio.strftime('%H:%M')} - "
                                f"{horario_conflictivo.hora_fin.strftime('%H:%M')}"
                            )
                        }
                    )
        
        return data
    
    def create(self, validated_data):
        """Crear horario asignando empresa y espacio automáticamente."""
        empresa = self.context.get("empresa")
        espacio_trabajo = self.context.get("espacio_trabajo")
        
        horario = HorarioEspacioTrabajo.objects.create(
            empresa=empresa,
            espacio_trabajo=espacio_trabajo,
            **validated_data
        )
        return horario


class HorarioEspacioTrabajoEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un horario existente.
    
    Campos permitidos:
    - dia_semana
    - hora_inicio
    - hora_fin
    - activo
    
    No se puede cambiar:
    - empresa
    - espacio_trabajo
    
    Validaciones:
    - hora_inicio < hora_fin
    - Si el horario está activo o será activado, valida NO solapamiento
    """
    
    class Meta:
        model = HorarioEspacioTrabajo
        fields = [
            "dia_semana",
            "hora_inicio",
            "hora_fin",
            "activo",
        ]
    
    def validate_dia_semana(self, value):
        """Validar que el día sea válido (0-6)."""
        if value < 0 or value > 6:
            raise serializers.ValidationError(
                "El día de la semana debe estar entre 0 (Lunes) y 6 (Domingo)."
            )
        return value
    
    def validate(self, data):
        """
        Validar que hora_inicio < hora_fin y que no haya solapamiento 
        con otros horarios activos del mismo espacio y día
        (excluyendo el horario siendo editado).
        
        La validación de solapamiento se aplica si:
        - El horario está activo actualmente, O
        - El horario SERÁ activado por esta edición
        """
        hora_inicio = data.get("hora_inicio", self.instance.hora_inicio if self.instance else None)
        hora_fin = data.get("hora_fin", self.instance.hora_fin if self.instance else None)
        dia_semana = data.get("dia_semana", self.instance.dia_semana if self.instance else None)
        
        # Determinar si el horario estará activo después de la edición
        nuevo_activo = data.get("activo", self.instance.activo if self.instance else True)
        
        # Validar rango de horas
        if hora_inicio and hora_fin and hora_inicio >= hora_fin:
            raise serializers.ValidationError(
                {"hora_fin": "La hora de fin debe ser mayor que la hora de inicio."}
            )
        
        # Validar solapamiento solo si el horario estará activo
        if nuevo_activo and dia_semana is not None and hora_inicio and hora_fin and self.instance:
            espacio_trabajo = self.instance.espacio_trabajo
            
            hay_conflicto, horario_conflictivo = _validar_solapamiento_horario(
                espacio_trabajo=espacio_trabajo,
                dia_semana=dia_semana,
                hora_inicio=hora_inicio,
                hora_fin=hora_fin,
                horario_id_excluir=self.instance.id  # Excluir el horario actual
            )
            
            if hay_conflicto:
                raise serializers.ValidationError(
                    {
                        "hora_inicio": (
                            f"Ya existe un horario activo que se solapa con el rango indicado: "
                            f"{horario_conflictivo.hora_inicio.strftime('%H:%M')} - "
                            f"{horario_conflictivo.hora_fin.strftime('%H:%M')}"
                        )
                    }
                )
        
        return data


class HorarioEspacioTrabajoActivoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar el estado activo/inactivo de un horario.
    El motivo NO se guarda en el modelo, solo se usa para auditoría.
    
    CRUCIALMENTE: Valida que al activar un horario, no se solape con
    otros horarios activos del mismo espacio y día.
    
    Regla de negocio:
    - Puede haber horarios solapados registrados (mientras sean inactivos)
    - NO pueden existir dos horarios ACTIVOS solapados
    - Si se intenta activar un horario que se solapa con otro activo → ERROR
    """
    activo = serializers.BooleanField(
        required=True,
        help_text="Cambiar estado activo/inactivo del horario"
    )
    motivo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="Motivo del cambio de estado (opcional, solo para auditoría)"
    )
    
    class Meta:
        model = HorarioEspacioTrabajo
        fields = [
            "activo",
            "motivo",
        ]
    
    def validate(self, data):
        """
        Validar que:
        1. El estado cambie (no sea redundante)
        2. Si se intenta activar (activo=True), que NO haya solapamiento
           con otros horarios activos del mismo espacio y día
        
        Lógica:
        - Si se pasa de inactivo a activo: VALIDAR solapamiento
        - Si se pasa de activo a inactivo: PERMITIDO siempre (sin validación)
        - Si se intenta mantener el estado: ERROR
        """
        instance = self.instance
        nuevo_estado = data.get("activo")
        
        if not instance:
            raise serializers.ValidationError(
                "Este serializer solo se puede usar para editar un horario existente."
            )
        
        # 1. Validar que el estado cambie (no sea redundante)
        if instance.activo == nuevo_estado:
            raise serializers.ValidationError(
                f"El horario ya está {'activo' if nuevo_estado else 'inactivo'}. "
                f"No hay cambio que realizar."
            )
        
        # 2. Si se intenta ACTIVAR (pasar de inactivo a activo), validar NO solapamiento
        if nuevo_estado is True:  # Cambio de inactivo (False) a activo (True)
            hay_conflicto, horario_conflictivo = _validar_solapamiento_horario(
                espacio_trabajo=instance.espacio_trabajo,
                dia_semana=instance.dia_semana,
                hora_inicio=instance.hora_inicio,
                hora_fin=instance.hora_fin,
                horario_id_excluir=instance.id  # Excluir el horario actual
            )
            
            if hay_conflicto:
                dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
                dia_nombre = dias[instance.dia_semana]
                raise serializers.ValidationError(
                    {
                        "activo": (
                            f"No se puede activar este horario porque se sobrepone con otro horario "
                            f"activo del {dia_nombre} en el espacio '{instance.espacio_trabajo.nombre}'. "
                            f"Horario existente: {horario_conflictivo.hora_inicio.strftime('%H:%M')} - "
                            f"{horario_conflictivo.hora_fin.strftime('%H:%M')}"
                        )
                    }
                )
        
        # 3. Si se intenta DESACTIVAR (pasar de activo a inactivo): PERMITIDO siempre
        # No hay validación de solapamiento para desactivaciones
        
        return data
    
    def save(self, **kwargs):
        """Guardar solo activo, excluir el motivo."""
        # El motivo se usa en auditoría, no se guarda en el modelo
        self.validated_data.pop('motivo', None)
        return super().save(**kwargs)


class EspacioTrabajoListadoSerializer(serializers.ModelSerializer):
    """
    Serializer para listar espacios de trabajo.
    Incluye información básica y estado del espacio.
    """
    tipo_display = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    activo_display = serializers.SerializerMethodField()
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "id",
            "codigo",
            "nombre",
            "tipo",
            "tipo_display",
            "estado",
            "estado_display",
            "activo",
            "activo_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    
    def get_tipo_display(self, obj):
        """Retorna descripción del tipo."""
        from app.models import TipoEspacioTrabajo
        tipo_map = dict(TipoEspacioTrabajo.choices)
        return tipo_map.get(obj.tipo, obj.tipo)
    
    def get_estado_display(self, obj):
        """Retorna descripción del estado."""
        from app.models import EstadoEspacioTrabajo
        estado_map = dict(EstadoEspacioTrabajo.choices)
        return estado_map.get(obj.estado, obj.estado)
    
    def get_activo_display(self, obj):
        """Retorna versión legible del estado activo."""
        return "Activo" if obj.activo else "Inactivo"


class EspacioTrabajoDetalleSerializer(serializers.ModelSerializer):
    """
    Serializer para detalle completo de un espacio de trabajo.
    Incluye horarios relacionados y metadata de auditoría.
    """
    horarios = HorarioEspacioTrabajoListadoSerializer(many=True, read_only=True)
    tipo_display = serializers.SerializerMethodField()
    estado_display = serializers.SerializerMethodField()
    activo_display = serializers.SerializerMethodField()
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "id",
            "codigo",
            "nombre",
            "tipo",
            "tipo_display",
            "estado",
            "estado_display",
            "activo",
            "activo_display",
            "observaciones",
            "horarios",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "empresa", "created_at", "updated_at"]
    
    def get_tipo_display(self, obj):
        """Retorna descripción del tipo."""
        from app.models import TipoEspacioTrabajo
        tipo_map = dict(TipoEspacioTrabajo.choices)
        return tipo_map.get(obj.tipo, obj.tipo)
    
    def get_estado_display(self, obj):
        """Retorna descripción del estado."""
        from app.models import EstadoEspacioTrabajo
        estado_map = dict(EstadoEspacioTrabajo.choices)
        return estado_map.get(obj.estado, obj.estado)
    
    def get_activo_display(self, obj):
        """Retorna versión legible del estado activo."""
        return "Activo" if obj.activo else "Inactivo"


class EspacioTrabajoCreacionSerializer(serializers.ModelSerializer):
    """
    Serializer para crear un espacio de trabajo.
    
    Validaciones:
    - código único por empresa
    - nombre obligatorio
    - tipo válido
    """
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "codigo",
            "nombre",
            "tipo",
            "observaciones",
        ]
    
    def validate_codigo(self, value):
        """Validar que el código sea único por empresa."""
        empresa = self.context.get("empresa")
        
        if empresa and EspacioTrabajo.objects.filter(
            empresa=empresa,
            codigo=value
        ).exists():
            raise serializers.ValidationError(
                f"Ya existe un espacio con código '{value}' en esta empresa."
            )
        
        return value
    
    def validate_nombre(self, value):
        """Validar que el nombre no sea vacío."""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "El nombre del espacio es obligatorio."
            )
        return value
    
    def validate_tipo(self, value):
        """Validar que el tipo sea válido."""
        from app.models import TipoEspacioTrabajo
        
        if value not in dict(TipoEspacioTrabajo.choices):
            raise serializers.ValidationError(
                f"Tipo inválido. Valores permitidos: {', '.join(dict(TipoEspacioTrabajo.choices).keys())}"
            )
        
        return value
    
    def create(self, validated_data):
        """Crear espacio asignando empresa automáticamente."""
        empresa = self.context.get("empresa")
        espacio = EspacioTrabajo.objects.create(
            empresa=empresa,
            **validated_data
        )
        return espacio


class EspacioTrabajoEdicionSerializer(serializers.ModelSerializer):
    """
    Serializer para editar un espacio de trabajo.
    
    Campos permitidos:
    - codigo
    - nombre
    - tipo
    - observaciones
    - activo
    
    No se puede cambiar:
    - empresa
    - estado (usar endpoint específico)
    """
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "codigo",
            "nombre",
            "tipo",
            "observaciones",
            "activo",
        ]
    
    def validate_codigo(self, value):
        """Validar que el código siga siendo único por empresa."""
        empresa = self.context.get("empresa")
        instance = self.instance
        
        # Si el código cambió, verificar que el nuevo sea único
        if instance and instance.codigo != value:
            if empresa and EspacioTrabajo.objects.filter(
                empresa=empresa,
                codigo=value
            ).exists():
                raise serializers.ValidationError(
                    f"Ya existe un espacio con código '{value}' en esta empresa."
                )
        
        return value
    
    def validate_nombre(self, value):
        """Validar que el nombre no sea vacío."""
        if not value or not value.strip():
            raise serializers.ValidationError(
                "El nombre del espacio es obligatorio."
            )
        return value
    
    def validate_tipo(self, value):
        """Validar que el tipo sea válido."""
        from app.models import TipoEspacioTrabajo
        
        if value not in dict(TipoEspacioTrabajo.choices):
            raise serializers.ValidationError(
                f"Tipo inválido. Valores permitidos: {', '.join(dict(TipoEspacioTrabajo.choices).keys())}"
            )
        
        return value


class EspacioTrabajoEstadoSerializer(serializers.ModelSerializer):
    """
    Serializer para cambiar el estado de un espacio de trabajo.
    
    Estados válidos: DISPONIBLE, OCUPADO, MANTENIMIENTO, TIEMPO_EXTENDIDO
    El motivo NO se guarda en el modelo, solo se usa para auditoría.
    """
    motivo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="Motivo del cambio de estado (opcional, solo para auditoría)"
    )
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "estado",
            "motivo",
        ]
    
    def validate_estado(self, value):
        """Validar que el estado sea válido."""
        from app.models import EstadoEspacioTrabajo
        
        estado_map = dict(EstadoEspacioTrabajo.choices)
        if value not in estado_map:
            raise serializers.ValidationError(
                f"Estado inválido. Valores permitidos: {', '.join(estado_map.keys())}"
            )
        
        return value
    
    def validate(self, data):
        """Validar que el estado sea diferente al actual."""
        instance = self.instance
        nuevo_estado = data.get("estado")
        
        if instance and instance.estado == nuevo_estado:
            raise serializers.ValidationError(
                f"El espacio ya tiene el estado '{nuevo_estado}'."
            )
        
        return data
    
    def save(self, **kwargs):
        """Guardar solo el estado, excluir el motivo."""
        # El motivo se usa en auditoría, no se guarda en el modelo
        self.validated_data.pop('motivo', None)
        return super().save(**kwargs)


class EspacioTrabajoActivoSerializer(serializers.ModelSerializer):
    """
    Serializer para activar/inactivar un espacio de trabajo.
    El motivo NO se guarda en el modelo, solo se usa para auditoría.
    """
    motivo = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True,
        write_only=True,
        help_text="Motivo del cambio (opcional, solo para auditoría)"
    )
    
    class Meta:
        model = EspacioTrabajo
        fields = [
            "activo",
            "motivo",
        ]
    
    def validate(self, data):
        """Validar que el estado activo cambie."""
        instance = self.instance
        nuevo_estado = data.get("activo")
        
        if instance and instance.activo == nuevo_estado:
            raise serializers.ValidationError(
                f"El espacio ya está {'activo' if nuevo_estado else 'inactivo'}."
            )
        
        return data
    
    def save(self, **kwargs):
        """Guardar solo activo, excluir el motivo."""
        # El motivo se usa en auditoría, no se guarda en el modelo
        self.validated_data.pop('motivo', None)
        return super().save(**kwargs)
