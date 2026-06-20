import json
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging
from django.utils import timezone

from modulos.comunicacion_control_inteligencia.models import (
    CanalEntregaNotificacion,
    DispositivoPush,
    EstadoEntregaNotificacion,
    Notificacion,
    NotificacionEntrega,
)


def _get_firebase_app():
    if firebase_admin._apps:
        return firebase_admin.get_app()

    cred_file = os.getenv("FIREBASE_CREDENTIALS_FILE", "").strip()
    cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()

    if cred_json:
        cred_obj = credentials.Certificate(json.loads(cred_json))
    elif cred_file:
        cred_obj = credentials.Certificate(cred_file)
    else:
        raise RuntimeError(
            "Firebase Admin no configurado. Define FIREBASE_CREDENTIALS_FILE o FIREBASE_CREDENTIALS_JSON."
        )

    return firebase_admin.initialize_app(cred_obj)


def enviar_notificacion_push_usuario(
    *,
    empresa,
    usuario,
    titulo: str,
    mensaje: str,
    tipo: str,
    entidad_tipo: Optional[str] = None,
    entidad_id=None,
    data: Optional[dict] = None,
):
    notificacion = Notificacion.objects.create(
        empresa=empresa,
        usuario=usuario,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        entidad_tipo=entidad_tipo,
        entidad_id=entidad_id,
    )

    NotificacionEntrega.objects.create(
        empresa=empresa,
        notificacion=notificacion,
        canal=CanalEntregaNotificacion.WEB,
        estado=EstadoEntregaNotificacion.ENVIADO,
        destinatario=usuario.email,
        enviado_at=timezone.now(),
    )

    if not usuario.noti_push:
        return notificacion

    tokens = list(
        DispositivoPush.objects.filter(
            empresa=empresa,
            usuario=usuario,
            activo=True,
        ).values_list("token", flat=True)
    )
    if not tokens:
        return notificacion

    _get_firebase_app()

    for token in tokens:
        entrega = NotificacionEntrega.objects.create(
            empresa=empresa,
            notificacion=notificacion,
            canal=CanalEntregaNotificacion.PUSH,
            estado=EstadoEntregaNotificacion.PENDIENTE,
            destinatario=token,
        )

        try:
            message = messaging.Message(
                token=token,
                notification=messaging.Notification(title=titulo, body=mensaje),
                data={k: str(v) for k, v in (data or {}).items()},
            )
            messaging.send(message)
            entrega.estado = EstadoEntregaNotificacion.ENVIADO
            entrega.enviado_at = timezone.now()
            entrega.error_mensaje = ""
            entrega.save(update_fields=["estado", "enviado_at", "error_mensaje", "updated_at"])
        except Exception as exc:
            entrega.estado = EstadoEntregaNotificacion.FALLIDO
            entrega.error_mensaje = str(exc)[:500]
            entrega.save(update_fields=["estado", "error_mensaje", "updated_at"])
            error_lower = str(exc).lower()
            if "not registered" in error_lower or "requested entity was not found" in error_lower:
                DispositivoPush.objects.filter(
                    empresa=empresa,
                    usuario=usuario,
                    token=token,
                ).update(activo=False, updated_at=timezone.now())

    return notificacion
