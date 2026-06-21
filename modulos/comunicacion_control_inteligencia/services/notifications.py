from django.db import transaction

from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.comunicacion_control_inteligencia.services.push_notifications import (
    enviar_notificacion_push_usuario,
)


def obtener_usuarios_roles(empresa, roles):
    if not roles:
        return Usuario.objects.none()
    return Usuario.objects.filter(
        empresa=empresa,
        is_active=True,
        rol__nombre__in=list(roles),
    ).select_related("rol")


def obtener_usuarios_operativos(empresa):
    return obtener_usuarios_roles(
        empresa,
        [
            "ADMIN",
            "ASESOR DE SERVICIO",
            "ADMINISTRATIVO",
            "ALMACENERO",
        ],
    )


def normalizar_usuarios(usuarios, excluir_usuario_ids=None):
    excluir_usuario_ids = {str(uid) for uid in (excluir_usuario_ids or []) if uid}
    unicos = {}
    for usuario in usuarios or []:
        if not usuario or not getattr(usuario, "id", None):
            continue
        if str(usuario.id) in excluir_usuario_ids:
            continue
        if not getattr(usuario, "is_active", True):
            continue
        unicos[str(usuario.id)] = usuario
    return list(unicos.values())


def notificar_usuarios(
    *,
    empresa,
    usuarios,
    titulo,
    mensaje,
    tipo,
    entidad_tipo=None,
    entidad_id=None,
    data=None,
    excluir_usuario_ids=None,
):
    destinatarios = normalizar_usuarios(usuarios, excluir_usuario_ids=excluir_usuario_ids)
    notificaciones = []
    for usuario in destinatarios:
        notificaciones.append(
            enviar_notificacion_push_usuario(
                empresa=empresa,
                usuario=usuario,
                titulo=titulo,
                mensaje=mensaje,
                tipo=tipo,
                entidad_tipo=entidad_tipo,
                entidad_id=entidad_id,
                data=data,
            )
        )
    return notificaciones


def notificar_usuarios_on_commit(**kwargs):
    transaction.on_commit(lambda: notificar_usuarios(**kwargs))
