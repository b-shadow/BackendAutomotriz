"""ViewSet para el asistente IA multi-tenant."""

import logging

from django.conf import settings
from rest_framework import status, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, FormParser, MultiPartParser
from rest_framework.response import Response

from app.models import ConversacionIA, MensajeIA, AccionIA, RolMensajeIA, CanalConversacionIA
from app.serializers.ia import ConversacionIASerializer, MensajeIASerializer
from app.services.ia_service import call_llm, transcribe_audio

logger = logging.getLogger(__name__)


class IsAuthenticatedTenant(permissions.BasePermission):
    """Permite acceso a cualquier usuario autenticado del tenant actual."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        if not hasattr(request, "tenant") or request.user.empresa != request.tenant:
            return False
        return True


class AsistenteIAViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticatedTenant]

    def _get_active_conversation(self, request):
        conversation = ConversacionIA.objects.filter(
            empresa=request.tenant,
            usuario=request.user,
            estado="ACTIVA",
        ).order_by("-updated_at").first()
        if conversation:
            return conversation
        return ConversacionIA.objects.create(
            empresa=request.tenant,
            usuario=request.user,
            estado="ACTIVA",
            canal=CanalConversacionIA.WEB,
        )

    def _serialize_messages(self, conversation, limit=30):
        mensajes = (
            MensajeIA.objects.filter(conversacion=conversation)
            .order_by("-created_at")
        )[:limit]
        mensajes = list(reversed(list(mensajes)))
        return MensajeIASerializer(mensajes, many=True).data

    @action(detail=False, methods=["get"], url_path="active")
    def active(self, request, *args, **kwargs):
        conversation = self._get_active_conversation(request)
        return Response(
            {
                "conversation": ConversacionIASerializer(conversation).data,
                "messages": self._serialize_messages(conversation),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="message")
    def message(self, request, *args, **kwargs):
        content = (request.data.get("content") or "").strip()
        source = request.data.get("source", "text")
        if not content:
            return Response(
                {"error": "El mensaje no puede estar vacio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        conversation = self._get_active_conversation(request)

        MensajeIA.objects.create(
            empresa=request.tenant,
            conversacion=conversation,
            rol_mensaje=RolMensajeIA.USUARIO,
            contenido=content,
            metadata={"source": source},
        )

        history = self._serialize_messages(conversation, limit=12)
        llm_messages = []
        for msg in history:
            role = msg.get("rol_mensaje")
            if role == RolMensajeIA.USUARIO:
                llm_role = "user"
            elif role == RolMensajeIA.ASISTENTE:
                llm_role = "assistant"
            else:
                llm_role = "system"
            llm_messages.append({"role": llm_role, "content": msg.get("contenido", "")})

        role_name = request.user.rol.nombre if request.user.rol else ""
        llm_response = call_llm(llm_messages, role_name)

        assistant_text = llm_response.get("assistant_text", "")
        suggested_actions = llm_response.get("suggested_actions", [])

        MensajeIA.objects.create(
            empresa=request.tenant,
            conversacion=conversation,
            rol_mensaje=RolMensajeIA.ASISTENTE,
            contenido=assistant_text,
            metadata={"suggested_actions": suggested_actions},
        )

        acciones = []
        for action in suggested_actions:
            accion = AccionIA.objects.create(
                empresa=request.tenant,
                conversacion=conversation,
                usuario=request.user,
                accion=action.get("action", ""),
                parametros=action.get("params") or {},
                estado="PENDIENTE",
                requiere_confirmacion=bool(action.get("requires_confirmation", True)),
                resultado={},
            )
            acciones.append({
                "id": str(accion.id),
                **action,
            })

        return Response(
            {
                "conversation_id": str(conversation.id),
                "assistant_text": assistant_text,
                "suggested_actions": acciones,
                "requires_confirmation": llm_response.get("requires_confirmation", True),
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["post"], url_path="archive")
    def archive(self, request, *args, **kwargs):
        conversation_id = request.data.get("conversation_id")
        conversation = None
        if conversation_id:
            conversation = ConversacionIA.objects.filter(
                id=conversation_id,
                empresa=request.tenant,
                usuario=request.user,
            ).first()
        if conversation is None:
            conversation = ConversacionIA.objects.filter(
                empresa=request.tenant,
                usuario=request.user,
                estado="ACTIVA",
            ).order_by("-updated_at").first()
        if conversation is None:
            return Response(
                {"mensaje": "No hay conversacion activa."},
                status=status.HTTP_200_OK,
            )
        conversation.estado = "ARCHIVADA"
        conversation.save(update_fields=["estado", "updated_at"])
        return Response(
            {"mensaje": "Conversacion archivada."},
            status=status.HTTP_200_OK,
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="transcribe",
        parser_classes=[MultiPartParser, FormParser, JSONParser],
    )
    def transcribe(self, request, *args, **kwargs):
        audio_file = request.FILES.get("audio")
        if audio_file is None:
            return Response(
                {"error": "No se recibio archivo de audio."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            transcription = transcribe_audio(audio_file)
        except Exception as exc:
            logger.exception("Error transcribiendo audio en /ia/transcribe: %s", exc)
            payload = {"error": "No se pudo transcribir el audio."}
            if settings.DEBUG:
                payload["detail"] = str(exc)
            return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        conversation = self._get_active_conversation(request)
        MensajeIA.objects.create(
            empresa=request.tenant,
            conversacion=conversation,
            rol_mensaje=RolMensajeIA.USUARIO,
            contenido=transcription,
            metadata={"source": "voice"},
        )

        return Response(
            {
                "conversation_id": str(conversation.id),
                "text": transcription,
            },
            status=status.HTTP_200_OK,
        )
