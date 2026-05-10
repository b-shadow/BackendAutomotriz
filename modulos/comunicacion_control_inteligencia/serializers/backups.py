import datetime

from rest_framework import serializers

from modulos.comunicacion_control_inteligencia.models import (
    BackupEmpresa,
    ProgramacionBackupEmpresa,
)


class BackupEmpresaSerializer(serializers.ModelSerializer):
    class Meta:
        model = BackupEmpresa
        fields = [
            'id',
            'empresa',
            'estado',
            'tipo',
            'alcance',
            'solicitado_por',
            'iniciado_at',
            'completado_at',
            'archivo_path',
            'tamano_bytes',
            'error',
            'metadata',
        ]
        read_only_fields = fields


class ProgramacionBackupSerializer(serializers.ModelSerializer):
    class SafeTimeField(serializers.TimeField):
        def to_representation(self, value):
            if isinstance(value, datetime.datetime):
                value = value.time()
            return super().to_representation(value)

    hora_ejecucion = SafeTimeField()

    class Meta:
        model = ProgramacionBackupEmpresa
        fields = [
            'activo',
            'frecuencia',
            'intervalo_dias',
            'hora_ejecucion',
            'tolera_compensacion',
            'ultima_ejecucion_at',
            'proxima_ejecucion_at',
        ]
        read_only_fields = ['ultima_ejecucion_at', 'proxima_ejecucion_at']


class CrearBackupSerializer(serializers.Serializer):
    alcance = serializers.ChoiceField(choices=['TENANT_COMPLETO'], default='TENANT_COMPLETO')


class RestaurarBackupSerializer(serializers.Serializer):
    confirmacion = serializers.CharField(max_length=100)
