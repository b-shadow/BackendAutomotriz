"""Servicios para el asistente IA (Groq LLM + transcripcion)."""

import json
import logging
import os
from typing import Any, Dict, List

try:
    from groq import Groq
except Exception:  # pragma: no cover - dependencia opcional en desarrollo
    Groq = None

logger = logging.getLogger(__name__)

DEFAULT_CHAT_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
DEFAULT_TRANSCRIPTION_MODEL = os.environ.get(
    "GROQ_TRANSCRIPTION_MODEL",
    "whisper-large-v3"
)


ACTION_CATALOG = {
    "citas.list": {
        "title": "Listar citas",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.detail": {
        "title": "Ver detalle de cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.create": {
        "title": "Crear cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.update": {
        "title": "Editar cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.cancel": {
        "title": "Cancelar cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.reprogramar": {
        "title": "Reprogramar cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "citas.change_state": {
        "title": "Cambiar estado de cita",
        "roles": ["ADMIN", "ASESOR DE SERVICIO"],
    },
    "vehiculos.list": {
        "title": "Listar vehiculos",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "vehiculos.detail": {
        "title": "Ver detalle de vehiculo",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "vehiculos.create": {
        "title": "Crear vehiculo",
        "roles": ["ADMIN", "ASESOR DE SERVICIO", "USUARIO"],
    },
    "vehiculos.update": {
        "title": "Editar vehiculo",
        "roles": ["ADMIN", "ASESOR DE SERVICIO"],
    },
    "vehiculos.change_state": {
        "title": "Cambiar estado de vehiculo",
        "roles": ["ADMIN", "ASESOR DE SERVICIO"],
    },
    "usuarios.list": {
        "title": "Listar usuarios",
        "roles": ["ADMIN"],
    },
    "usuarios.detail": {
        "title": "Ver detalle de usuario",
        "roles": ["ADMIN"],
    },
    "usuarios.change_role": {
        "title": "Cambiar rol de usuario",
        "roles": ["ADMIN"],
    },
    "usuarios.activate": {
        "title": "Activar usuario",
        "roles": ["ADMIN"],
    },
    "usuarios.deactivate": {
        "title": "Desactivar usuario",
        "roles": ["ADMIN"],
    },
    "auditoria.list": {
        "title": "Listar auditoria",
        "roles": ["ADMIN"],
    },
    "auditoria.detail": {
        "title": "Ver detalle de auditoria",
        "roles": ["ADMIN"],
    },
}


def get_groq_client():
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key or Groq is None:
        return None
    return Groq(api_key=api_key)


def get_allowed_actions(role_name: str) -> List[str]:
    normalized = (role_name or "").upper().strip()
    allowed = []
    for action, config in ACTION_CATALOG.items():
        if normalized in config["roles"]:
            allowed.append(action)
    return allowed


def build_system_prompt(role_name: str, allowed_actions: List[str]) -> str:
    allowed_text = ", ".join(allowed_actions) if allowed_actions else "NINGUNA"
    return (
        "Eres un asistente virtual para un sistema automotriz. "
        "Respondes en espanol, tono formal, frases concisas. "
        "Nunca afirmes que una accion fue ejecutada. "
        "Si propones una accion, pide confirmacion antes de ejecutarla. "
        "Solo puedes sugerir acciones permitidas para el rol del usuario. "
        "Devuelve SIEMPRE un JSON valido con este esquema:\n"
        "{\n"
        "  \"assistant_text\": \"...\",\n"
        "  \"suggested_actions\": [\n"
        "    {\"action\": \"citas.create\", \"title\": \"Crear cita\", "
        "\"params\": {...}, \"preview_steps\": [\"Paso 1\"], "
        "\"requires_confirmation\": true}\n"
        "  ],\n"
        "  \"requires_confirmation\": true\n"
        "}\n"
        "Si el usuario pide una accion no permitida, responde con assistant_text "
        "explicando que no tiene permisos y suggested_actions vacio.\n"
        f"Rol actual: {role_name or 'DESCONOCIDO'}.\n"
        f"Acciones permitidas: {allowed_text}."
    )


def parse_llm_json(content: str) -> Dict[str, Any]:
    if not content:
        raise ValueError("Respuesta vacia")
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start:end + 1]
            return json.loads(snippet)
        raise


def call_llm(messages: List[Dict[str, str]], role_name: str) -> Dict[str, Any]:
    client = get_groq_client()
    if client is None:
        return {
            "assistant_text": "No pude procesar tu solicitud en este momento.",
            "suggested_actions": [],
            "requires_confirmation": False,
        }

    allowed_actions = get_allowed_actions(role_name)
    system_prompt = build_system_prompt(role_name, allowed_actions)
    llm_messages = [{"role": "system", "content": system_prompt}] + messages

    try:
        response = client.chat.completions.create(
            model=DEFAULT_CHAT_MODEL,
            messages=llm_messages,
            temperature=0.2,
            max_tokens=600,
        )
        content = response.choices[0].message.content
        if not content:
            return {
                "assistant_text": "No recibi respuesta del modelo.",
                "suggested_actions": [],
                "requires_confirmation": False,
            }

        try:
            parsed = parse_llm_json(content)
            return normalize_llm_response(parsed, allowed_actions)
        except json.JSONDecodeError:
            return {
                "assistant_text": content.strip(),
                "suggested_actions": [],
                "requires_confirmation": False,
            }
    except Exception as exc:
        logger.exception("Error llamando Groq LLM: %s", exc)
        return {
            "assistant_text": "Ocurrio un error al generar la respuesta.",
            "suggested_actions": [],
            "requires_confirmation": False,
        }


def normalize_llm_response(data: Dict[str, Any], allowed_actions: List[str]) -> Dict[str, Any]:
    assistant_text = data.get("assistant_text", "")
    suggested_actions = data.get("suggested_actions", []) or []
    filtered_actions = []
    for item in suggested_actions:
        action = item.get("action")
        if action and action in allowed_actions:
            filtered_actions.append({
                "action": action,
                "title": item.get("title") or ACTION_CATALOG.get(action, {}).get("title") or action,
                "params": item.get("params") or {},
                "preview_steps": [],
                "requires_confirmation": bool(item.get("requires_confirmation", True)),
            })
    if filtered_actions:
        requires_confirmation = bool(data.get("requires_confirmation", True))
        if requires_confirmation:
            assistant_text = (
                "Tengo una accion sugerida. "
                "Confirmala para ejecutarla."
            )
    else:
        requires_confirmation = bool(data.get("requires_confirmation", True))
    return {
        "assistant_text": assistant_text or "No tengo una respuesta en este momento.",
        "suggested_actions": filtered_actions,
        "requires_confirmation": requires_confirmation,
    }


def transcribe_audio(file_obj) -> str:
    client = get_groq_client()
    if client is None:
        raise RuntimeError("GROQ_API_KEY no configurada")

    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    filename = getattr(file_obj, "name", "audio.wav")
    content_type = getattr(file_obj, "content_type", None)

    response = client.audio.transcriptions.create(
        file=(filename, file_obj, content_type),
        model=DEFAULT_TRANSCRIPTION_MODEL,
    )
    return getattr(response, "text", "")
