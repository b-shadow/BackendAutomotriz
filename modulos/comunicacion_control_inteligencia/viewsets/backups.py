import os

from django.conf import settings
from django.http import FileResponse
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from modulos.comunicacion_control_inteligencia.models import BackupEmpresa, ProgramacionBackupEmpresa
from modulos.comunicacion_control_inteligencia.serializers.backups import (
    BackupEmpresaSerializer,
    ProgramacionBackupSerializer,
    CrearBackupSerializer,
    RestaurarBackupSerializer,
)
from modulos.comunicacion_control_inteligencia.services.backups import BackupService
from modulos.administracion_acceso_configuracion.services.auditoria_service import (
    registrar_evento_on_commit,
    AccionAuditoria,
)
from modulos.comunicacion_control_inteligencia.services import (
    notificar_usuarios_on_commit,
    obtener_usuarios_roles,
)


class IsAuthenticatedTenant(permissions.BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, 'tenant') or request.user.empresa != request.tenant:
            return False
        return True


class PuedeGestionarBackup(permissions.BasePermission):
    def has_permission(self, request, view):
        rol = request.user.rol.nombre if request.user and request.user.rol else None
        return rol == 'ADMIN'


class BackupEmpresaViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BackupEmpresaSerializer
    permission_classes = [IsAuthenticatedTenant]

    def get_permissions(self):
        if self.action in ['crear_manual', 'restaurar', 'ejecutar_pendientes']:
            return [IsAuthenticatedTenant(), PuedeGestionarBackup()]
        return [IsAuthenticatedTenant()]

    def get_queryset(self):
        return BackupEmpresa.objects.filter(empresa=self.request.tenant).order_by('-iniciado_at')

    def list(self, request, *args, **kwargs):
        BackupService.run_due_backups_for_empresa(request.tenant)
        return super().list(request, *args, **kwargs)

    @action(detail=False, methods=['post'], url_path='crear-manual')
    def crear_manual(self, request, **kwargs):
        serializer = CrearBackupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            backup = BackupService.ejecutar_backup_manual(
                empresa=request.tenant,
                usuario=request.user,
                alcance=serializer.validated_data['alcance'],
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='BackupEmpresa',
            entidad_id=str(backup.id),
            descripcion='Backup manual ejecutado',
            metadata={'tipo': backup.tipo, 'estado': backup.estado},
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=list(obtener_usuarios_roles(request.tenant, ["ADMIN"])),
            titulo="Backup manual ejecutado",
            mensaje=f"Se ejecutó un backup manual con estado {backup.estado}.",
            tipo="backup_manual_ejecutado",
            entidad_tipo="BackupEmpresa",
            entidad_id=backup.id,
            data={"backup_id": str(backup.id), "estado": backup.estado},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(BackupEmpresaSerializer(backup).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get', 'put'], url_path='programacion')
    def programacion(self, request, **kwargs):
        if request.method.lower() == 'get':
            prog, _ = ProgramacionBackupEmpresa.objects.get_or_create(empresa=request.tenant)
            return Response(ProgramacionBackupSerializer(prog).data, status=status.HTTP_200_OK)

        if not PuedeGestionarBackup().has_permission(request, self):
            return Response({'detail': 'No tiene permiso para esta accion.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ProgramacionBackupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        prog = BackupService.actualizar_programacion(
            empresa=request.tenant,
            activo=data['activo'],
            frecuencia=data['frecuencia'],
            intervalo_dias=data.get('intervalo_dias', 1),
            hora_ejecucion=data['hora_ejecucion'],
            tolera_compensacion=data.get('tolera_compensacion', True),
        )

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='ProgramacionBackupEmpresa',
            entidad_id=str(prog.id),
            descripcion='Programacion de backup actualizada',
            metadata={'activo': prog.activo, 'frecuencia': prog.frecuencia, 'intervalo_dias': prog.intervalo_dias},
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=list(obtener_usuarios_roles(request.tenant, ["ADMIN"])),
            titulo="Programación de backup actualizada",
            mensaje=f"Se actualizó la programación de backups. Activo: {'sí' if prog.activo else 'no'}.",
            tipo="backup_programacion_actualizada",
            entidad_tipo="ProgramacionBackupEmpresa",
            entidad_id=prog.id,
            data={"programacion_id": str(prog.id), "activo": str(prog.activo)},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(ProgramacionBackupSerializer(prog).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='ejecutar-pendientes')
    def ejecutar_pendientes(self, request, **kwargs):
        created = BackupService.run_due_backups_for_empresa(request.tenant, force=True)
        if created:
            notificar_usuarios_on_commit(
                empresa=request.tenant,
                usuarios=list(obtener_usuarios_roles(request.tenant, ["ADMIN"])),
                titulo="Backups pendientes ejecutados",
                mensaje=f"Se ejecutaron {len(created)} backups pendientes o forzados.",
                tipo="backups_pendientes_ejecutados",
                entidad_tipo="BackupEmpresa",
                entidad_id=created[0].id,
                data={"cantidad": str(len(created))},
                excluir_usuario_ids=[request.user.id],
            )
        return Response({'ejecutados': len(created)}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'], url_path='descargar')
    def descargar(self, request, pk=None, **kwargs):
        backup = self.get_object()
        if not backup.archivo_path:
            return Response({'error': 'Este backup no tiene archivo disponible.'}, status=status.HTTP_404_NOT_FOUND)

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            return Response({'error': 'MEDIA_ROOT no esta configurado.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        normalized_path = str(backup.archivo_path).replace('\\', os.sep).replace('/', os.sep)
        full = os.path.join(media_root, normalized_path)
        if not os.path.exists(full):
            return Response({'error': 'Archivo de backup no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            handle = open(full, 'rb')
        except OSError:
            return Response({'error': 'No se pudo abrir el archivo de backup.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return FileResponse(handle, as_attachment=True, filename=os.path.basename(full))
    @action(detail=True, methods=['get'], url_path='visualizar')
    def visualizar(self, request, pk=None, **kwargs):
        backup = self.get_object()
        if not backup.archivo_path:
            return Response({'error': 'Este backup no tiene archivo disponible.'}, status=status.HTTP_404_NOT_FOUND)

        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if not media_root:
            return Response({'error': 'MEDIA_ROOT no esta configurado.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        normalized_path = str(backup.archivo_path).replace('\\', os.sep).replace('/', os.sep)
        full = os.path.join(media_root, normalized_path)
        if not os.path.exists(full):
            return Response({'error': 'Archivo de backup no encontrado.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            payload = BackupService._read_backup_payload(backup)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            return Response({'error': 'No se pudo leer el contenido del backup.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(payload, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'], url_path='restaurar')
    def restaurar(self, request, pk=None, **kwargs):
        backup = self.get_object()
        serializer = RestaurarBackupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data['confirmacion'] != 'RESTAURAR':
            return Response({'error': 'Confirmacion invalida. Debe enviar RESTAURAR.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resultado = BackupService.restaurar_backup_tenant(
                empresa=request.tenant,
                backup=backup,
                usuario=request.user,
            )
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({'error': f'No se pudo restaurar el backup: {exc}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        registrar_evento_on_commit(
            empresa=request.tenant,
            usuario=request.user,
            accion=AccionAuditoria.CITA_ACTUALIZADA,
            entidad_tipo='BackupEmpresa',
            entidad_id=str(backup.id),
            descripcion='Restauracion de backup ejecutada',
            metadata={'backup_id': str(backup.id), 'resultado': resultado},
        )
        notificar_usuarios_on_commit(
            empresa=request.tenant,
            usuarios=list(obtener_usuarios_roles(request.tenant, ["ADMIN"])),
            titulo="Restauración de backup ejecutada",
            mensaje="Se completó una restauración de backup sobre la empresa actual.",
            tipo="backup_restaurado",
            entidad_tipo="BackupEmpresa",
            entidad_id=backup.id,
            data={"backup_id": str(backup.id)},
            excluir_usuario_ids=[request.user.id],
        )

        return Response(
            {
                'mensaje': 'Restauracion completada para la empresa actual.',
                'backup_id': str(backup.id),
                'resultado': resultado,
            },
            status=status.HTTP_200_OK,
        )

