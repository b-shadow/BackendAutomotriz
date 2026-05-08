import gzip
import json
import os
from datetime import datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from modulos.administracion_acceso_configuracion.models import Empresa, Usuario
from modulos.comunicacion_control_inteligencia.models import (
    BackupEmpresa,
    ProgramacionBackupEmpresa,
    EstadoBackup,
    TipoBackup,
    AlcanceBackup,
)


class BackupService:
    CHECK_INTERVAL_SECONDS = 60
    _last_check_by_empresa = {}
    EXCLUDED_MODELS = {
        'comunicacion_control_inteligencia.BackupEmpresa',
        'comunicacion_control_inteligencia.ProgramacionBackupEmpresa',
    }

    @staticmethod
    def _to_serializable(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return obj

    @staticmethod
    def _backup_dir(empresa):
        path = os.path.join(settings.MEDIA_ROOT, 'backups', empresa.slug)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _build_snapshot_tenant(empresa):
        payload = {
            'empresa_id': str(empresa.id),
            'empresa_slug': empresa.slug,
            'capturado_at': timezone.now().isoformat(),
            'modelos': {},
        }

        for model in apps.get_models():
            try:
                field_names = {f.name for f in model._meta.fields}
                if 'empresa' not in field_names:
                    continue
                qs = model.objects.filter(empresa=empresa)
                records = list(qs.values())
                if not records:
                    continue
                model_key = f"{model._meta.app_label}.{model.__name__}"
                if model_key in BackupService.EXCLUDED_MODELS:
                    continue
                payload['modelos'][model_key] = records
            except Exception:
                continue

        return payload

    @staticmethod
    def _read_backup_payload(backup):
        if not backup.archivo_path:
            raise ValueError('Este backup no tiene archivo asociado.')

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            raise ValueError('MEDIA_ROOT no esta configurado.')

        normalized_path = str(backup.archivo_path).replace('\\', os.sep).replace('/', os.sep)
        full = os.path.join(media_root, normalized_path)
        if not os.path.exists(full):
            raise ValueError('Archivo de backup no encontrado.')

        if full.endswith('.gz'):
            with gzip.open(full, 'rt', encoding='utf-8') as fh:
                return json.load(fh)
        with open(full, 'r', encoding='utf-8') as fh:
            return json.load(fh)

    @staticmethod
    def _resolve_model(model_key):
        try:
            app_label, model_name = model_key.split('.', 1)
            return apps.get_model(app_label, model_name)
        except Exception:
            return None

    @staticmethod
    @transaction.atomic
    def restaurar_backup_tenant(empresa, backup, usuario=None):
        payload = BackupService._read_backup_payload(backup)
        if payload.get('empresa_slug') != empresa.slug:
            raise ValueError('El backup no corresponde a esta empresa.')

        modelos_payload = payload.get('modelos', {})
        model_entries = []
        for model_key, records in modelos_payload.items():
            if model_key in BackupService.EXCLUDED_MODELS:
                continue
            model = BackupService._resolve_model(model_key)
            if not model:
                continue
            field_names = {f.name for f in model._meta.fields}
            if 'empresa' not in field_names:
                continue
            model_entries.append((model_key, model, records))

        # Eliminar data existente de esta empresa sin tocar otros tenants.
        for _, model, _ in reversed(model_entries):
            model.objects.filter(empresa=empresa).delete()

        restored_counts = {}
        for model_key, model, records in model_entries:
            created = 0
            for data in records:
                payload_row = dict(data)
                payload_row['empresa_id'] = empresa.id
                try:
                    model.objects.create(**payload_row)
                    created += 1
                except Exception:
                    # Si algun registro puntual falla, continuamos para no abortar toda la restauracion.
                    continue
            restored_counts[model_key] = created

        return {
            'empresa_slug': empresa.slug,
            'capturado_at': payload.get('capturado_at'),
            'modelos_restaurados': restored_counts,
            'total_registros': sum(restored_counts.values()),
            'restaurado_at': timezone.now().isoformat(),
            'restaurado_por': str(usuario.id) if usuario else None,
        }

    @staticmethod
    @transaction.atomic
    def ejecutar_backup_manual(empresa, usuario=None, alcance=AlcanceBackup.TENANT_COMPLETO):
        return BackupService._ejecutar_backup(empresa=empresa, usuario=usuario, tipo=TipoBackup.MANUAL, alcance=alcance)

    @staticmethod
    @transaction.atomic
    def _ejecutar_backup(empresa, usuario=None, tipo=TipoBackup.AUTOMATICO, alcance=AlcanceBackup.TENANT_COMPLETO):
        en_proceso = BackupEmpresa.objects.filter(empresa=empresa, estado=EstadoBackup.EN_PROCESO).exists()
        if en_proceso:
            raise ValueError('Ya existe un backup en proceso para esta empresa.')

        backup = BackupEmpresa.objects.create(
            empresa=empresa,
            estado=EstadoBackup.EN_PROCESO,
            tipo=tipo,
            alcance=alcance,
            solicitado_por=usuario,
            metadata={},
        )

        try:
            snapshot = BackupService._build_snapshot_tenant(empresa)
            backup_dir = BackupService._backup_dir(empresa)
            fname = f"backup_{empresa.slug}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json.gz"
            fpath = os.path.join(backup_dir, fname)

            with gzip.open(fpath, 'wt', encoding='utf-8') as gz:
                json.dump(snapshot, gz, cls=DjangoJSONEncoder)

            size = os.path.getsize(fpath)
            backup.estado = EstadoBackup.COMPLETADO
            backup.completado_at = timezone.now()
            backup.archivo_path = os.path.relpath(fpath, settings.MEDIA_ROOT)
            backup.tamano_bytes = size
            backup.metadata = {
                'modelos_count': len(snapshot.get('modelos', {})),
            }
            backup.save(update_fields=['estado', 'completado_at', 'archivo_path', 'tamano_bytes', 'metadata'])
            return backup
        except Exception as exc:
            backup.estado = EstadoBackup.FALLIDO
            backup.error = str(exc)
            backup.completado_at = timezone.now()
            backup.save(update_fields=['estado', 'error', 'completado_at'])
            raise

    @staticmethod
    def calcular_proxima_ejecucion(programacion, base_dt=None):
        base = base_dt or timezone.now()
        hora = programacion.hora_ejecucion
        candidate = base.replace(hour=hora.hour, minute=hora.minute, second=0, microsecond=0)

        if programacion.frecuencia == 'DIARIO':
            if candidate <= base:
                candidate = candidate + timedelta(days=1)
            return candidate

        intervalo = max(programacion.intervalo_dias or 1, 1)
        if programacion.ultima_ejecucion_at:
            next_dt = programacion.ultima_ejecucion_at + timedelta(days=intervalo)
            next_dt = next_dt.replace(hour=hora.hour, minute=hora.minute, second=0, microsecond=0)
            if next_dt <= base:
                while next_dt <= base:
                    next_dt += timedelta(days=intervalo)
            return next_dt

        if candidate <= base:
            candidate += timedelta(days=intervalo)
        return candidate

    @staticmethod
    def actualizar_programacion(empresa, activo, frecuencia, intervalo_dias, hora_ejecucion, tolera_compensacion=True):
        prog, _ = ProgramacionBackupEmpresa.objects.get_or_create(empresa=empresa)
        prog.activo = bool(activo)
        prog.frecuencia = frecuencia
        prog.intervalo_dias = max(int(intervalo_dias or 1), 1)
        prog.hora_ejecucion = hora_ejecucion
        prog.tolera_compensacion = bool(tolera_compensacion)
        if prog.activo:
            prog.proxima_ejecucion_at = BackupService.calcular_proxima_ejecucion(prog)
        else:
            prog.proxima_ejecucion_at = None
        prog.save()
        return prog

    @staticmethod
    def run_due_backups_for_empresa(empresa, force=False):
        now = timezone.now()
        key = str(empresa.id)
        if not force:
            last = BackupService._last_check_by_empresa.get(key)
            if last and (now - last).total_seconds() < BackupService.CHECK_INTERVAL_SECONDS:
                return []
        BackupService._last_check_by_empresa[key] = now

        try:
            prog = ProgramacionBackupEmpresa.objects.get(empresa=empresa)
        except ProgramacionBackupEmpresa.DoesNotExist:
            return []

        if not prog.activo or not prog.proxima_ejecucion_at:
            return []

        created = []
        while prog.proxima_ejecucion_at and prog.proxima_ejecucion_at <= timezone.now():
            tipo = TipoBackup.AUTOMATICO
            if prog.proxima_ejecucion_at < timezone.now() - timedelta(minutes=1):
                tipo = TipoBackup.COMPENSACION

            if not prog.tolera_compensacion and tipo == TipoBackup.COMPENSACION:
                prog.proxima_ejecucion_at = BackupService.calcular_proxima_ejecucion(prog, base_dt=timezone.now())
                prog.save(update_fields=['proxima_ejecucion_at', 'updated_at'])
                break

            backup = BackupService._ejecutar_backup(empresa=empresa, usuario=None, tipo=tipo)
            created.append(backup)
            prog.ultima_ejecucion_at = timezone.now()
            prog.proxima_ejecucion_at = BackupService.calcular_proxima_ejecucion(prog)
            prog.save(update_fields=['ultima_ejecucion_at', 'proxima_ejecucion_at', 'updated_at'])

            # Evitar bucles infinitos en caso de data corrupta
            if len(created) > 30:
                break

        return created
