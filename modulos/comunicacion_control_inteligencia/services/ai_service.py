import os
from typing import List, Dict, Any, Optional
from groq import Groq
from django.conf import settings

class AIService:
    """
    Servicio para interactuar con la API de Groq para procesamiento de lenguaje natural
    y transcripción de voz.
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.transcription_model = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
        
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no está configurada en las variables de entorno.")
            
        self.client = Groq(api_key=self.api_key)

    def get_chat_response(self, messages: List[Dict[str, str]], user_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Obtiene una respuesta de chat de Groq.
        """
        system_prompt = self._build_system_prompt(user_context)
        
        full_messages = [
            {"role": "system", "content": system_prompt}
        ] + messages

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=full_messages,
                temperature=0.7,
                max_tokens=1024,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            return {
                "content": content,
                "model": self.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                }
            }
        except Exception as e:
            # En producción, usar logging
            print(f"Error en AIService.get_chat_response: {str(e)}")
            return {
                "error": str(e),
                "content": "Lo siento, he tenido un problema técnico al procesar tu solicitud. Por favor, inténtalo de nuevo en un momento."
            }

    def transcribe_audio(self, audio_file_path: str) -> str:
        """
        Transcribe un archivo de audio a texto usando Whisper en Groq.
        """
        try:
            with open(audio_file_path, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(os.path.basename(audio_file_path), file.read()),
                    model=self.transcription_model,
                    language="es",
                    response_format="text"
                )
            return transcription
        except Exception as e:
            print(f"Error en AIService.transcribe_audio: {str(e)}")
            return ""

    def _build_system_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Construye el prompt de sistema para dar contexto a la IA.
        """
        context_str = ""
        if context:
            context_str = f"\nContexto del usuario:\n- Empresa: {context.get('tenant_name')}\n- Usuario: {context.get('user_name')}\n- Rol: {context.get('user_role')}\n"
            if context.get('owners_list'):
                context_str += f"- Propietarios disponibles: {', '.join(context.get('owners_list'))}\n"

        from .prompts import get_full_prompt
        prompt = get_full_prompt(context_str)
        return prompt
