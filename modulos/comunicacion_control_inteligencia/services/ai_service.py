import os
from typing import List, Dict, Any, Optional
from groq import Groq
from django.conf import settings
import instructor
from .schemas import IAAssistantResponse, IntentClassification

class AIService:
    """
    Servicio para interactuar con la API de Groq usando Instructor para validación Pydantic.
    Implementa el patrón Router-Agente para optimizar tokens y modularizar reglas.
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        # Modelo ligero exclusivo para el enrutador (solo clasifica en 6 categorías)
        self.router_model = os.getenv("GROQ_ROUTER_MODEL", "llama-3.1-8b-instant")
        self.transcription_model = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
        
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no está configurada en las variables de entorno.")
            
        self.raw_client = Groq(api_key=self.api_key)
        self.client = instructor.from_groq(self.raw_client)

    def _route_intent(self, messages: List[Dict[str, str]]) -> str:
        """
        Fase 1: Enrutador rápido para detectar el módulo del cual está hablando el usuario.
        Usa los últimos 3 intercambios para evitar confusión por contexto previo.
        """
        if not messages:
            return "GENERAL"

        # Tomar los últimos 3 mensajes para dar contexto al router
        recent = messages[-4:] if len(messages) >= 4 else messages
        context_lines = []
        for msg in recent:
            role_label = "Usuario" if msg['role'] == 'user' else "Asistente"
            context_lines.append(f"{role_label}: {msg['content'][:200]}")
        context_str = "\n".join(context_lines)

        router_prompt = f"""Clasifica el ÚLTIMO mensaje del usuario en uno de estos módulos de un SaaS de Taller Mecánico.
  IMPORTANTE: Clasifica como CONFIGURACION (catálogo de servicios) SOLO si el usuario dice literalmente "servicio", "horario", "espacio" o "nombre de empresa".
  IMPORTANTE: Palabras como "item", "ítem", "unitem", "repuesto", "insumo", "producto", "pieza", "tornillo", "llanta", o menciones a "inventario" y "stock" -> INVENTARIO. NUNCA lo mandes a CONFIGURACION.
  Clasifica como VEHICULOS_PLANES si se habla explícitamente de autos, placas, propietarios, dueños, o planes de mantenimiento de un vehículo.
  
  Módulos:
  - VEHICULOS_PLANES: Registrar autos, buscar por placa, ver/elegir propietarios, planes de mantenimiento de vehículo específico.
  - CITAS: Agendar, filtrar o buscar citas de taller.
  - CONFIGURACION: Crear/editar servicios del catálogo del taller, horarios, espacios de trabajo, nombre de empresa.
  - PERFIL_USUARIO: Nombres, teléfonos, contraseñas, preferencias del usuario.
  - REPORTES_BITACORA: Bitácoras, reportes PDF/Excel, logs de actividad, filtrar bitácora.
  - INVENTARIO: Registrar categorías, crear ítems de inventario (repuestos, insumos, productos), stock.
- PROVEEDORES: Añadir proveedores de la empresa.
- COMPRAS: Compras de insumos o repuestos.
- USUARIOS: Gestión de usuarios del sistema, añadir usuario, cambiar roles.
- BACKUP: Configuraciones de copias de seguridad de la base de datos.
- GENERAL: Saludos, preguntas generales, sin acción específica.

Conversación reciente:
{context_str}

Responde SOLO con el módulo correspondiente."""

        try:
            # Router usa modelo ligero 8B — solo clasifica en 6 categorías
            intent_res = self.client.chat.completions.create(
                model=self.router_model,
                messages=[{"role": "user", "content": router_prompt}],
                response_model=IntentClassification,
                temperature=0.0,
                max_tokens=20
            )
            return intent_res.intent
        except Exception as e:
            print(f"Error en _route_intent: {str(e)}")
            return "GENERAL"

    def get_chat_response(self, messages: List[Dict[str, str]], user_context: Optional[Dict[str, Any]] = None) -> IAAssistantResponse:
        """
        Fase 2: Obtiene una respuesta de chat estructurada inyectando solo el prompt del módulo.
        Incluye reintentos manuales con mensaje de corrección si el LLM usa un 'type' inválido.
        """
        intent = self._route_intent(messages)
        print(f"[AI Router] Intención detectada: {intent}")

        system_prompt = self._build_dynamic_prompt(intent, user_context)
        full_messages = [{"role": "system", "content": system_prompt}] + messages

        MAX_ATTEMPTS = 3
        last_error = None

        for attempt in range(MAX_ATTEMPTS):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=full_messages,
                    response_model=IAAssistantResponse,
                    temperature=0.1,
                    max_tokens=1024,
                )
                return response
            except Exception as e:
                last_error = e
                error_str = str(e)
                print(f"[AI Retry {attempt + 1}/{MAX_ATTEMPTS}] Error: {error_str[:300]}")

                # Si el error es de validación de tipo (LLM inventó una acción), inyectar corrección
                if "tool call validation failed" in error_str or "value must be one of" in error_str:
                    if attempt < MAX_ATTEMPTS - 1:
                        correction_msg = (
                            "CORRECCIÓN OBLIGATORIA: Tu respuesta anterior fue rechazada porque usaste "
                            "un 'type' de acción que NO EXISTE en el esquema. "
                            "Revisa la lista de ACCIONES PERMITIDAS y usa EXACTAMENTE uno de esos valores sin modificarlo. "
                            "Por ejemplo: para crear un servicio en el catálogo usa 'AGREGAR_SERVICIO', nunca 'REGISTRAR_SERVICIO'. "
                            "Responde de nuevo con el 'type' correcto."
                        )
                        full_messages = full_messages + [{"role": "user", "content": correction_msg}]
                        continue
                # Cualquier otro error: salir del bucle
                break

        print(f"Error en AIService.get_chat_response: {str(last_error)}")
        return IAAssistantResponse(
            message="Lo siento, he tenido un problema técnico al procesar tu solicitud. Por favor, inténtalo de nuevo en un momento.",
            options=[],
            suggested_actions=[],
            action=None
        )

    def transcribe_audio(self, audio_file) -> str:
        """
        Transcribe un archivo de audio a texto usando Whisper.
        """
        debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'transcribe_debug.log')
        try:
            if isinstance(audio_file, str):
                with open(audio_file, "rb") as file:
                    file_data = file.read()
                    filename = os.path.basename(audio_file)
            else:
                file_data = audio_file.read()
                filename = getattr(audio_file, 'name', 'audio.webm') or 'audio.webm'

            transcription = self.raw_client.audio.transcriptions.create(
                file=(filename, file_data),
                model="whisper-large-v3-turbo",
                language="es",
                prompt="Por favor, transcribe este audio en español. Ignora ruidos estáticos.",
                temperature=0.0,
                response_format="json"
            )
            return transcription.text
        except Exception as e:
            print(f"Error en AIService.transcribe_audio: {str(e)}")
            return ""

    def _build_dynamic_prompt(self, intent: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Construye el prompt de sistema inyectando solo las reglas y contexto necesarios para el intent.
        """
        # Contexto Base (siempre necesario)
        if context:
            form_data_str = str(context.get('current_form_data', {}))
            base_context = f"Empresa: {context.get('tenant_name')}\nUsuario: {context.get('user_name')} ({context.get('user_role')})\nDATOS DEL FORMULARIO YA RECOLECTADOS Y GUARDADOS: {form_data_str} (¡NO VUELVAS A PREGUNTAR AL USUARIO POR ESTOS DATOS, YA LOS TIENES!)"
        else:
            base_context = ""
        
        # Reglas de Oro Generales
        prompt = f"""
Eres AutoTaller AI, el asistente inteligente para un software SaaS de talleres mecánicos.
Contexto Base:
{base_context}

REGLAS GENERALES ESTRICTAS:
  1. Tu único propósito es ayudar al usuario a usar el sistema. Si te preguntan cosas ajenas, di que solo ayudas con el taller.
  2. NUNCA inventes IDs, placas o datos. Si el usuario ya te dio un dato, NO LO VUELVAS A PREGUNTAR.
  3. OBLIGATORIO: DEBES generar SIEMPRE el objeto 'action' con status="PENDIENTE" desde tu primer mensaje para abrir el formulario al usuario e ir pre-llenando los datos, incluso si no tienes ningún parámetro todavía. NUNCA respondas sin el objeto 'action' si el usuario pide realizar una acción.
  4. Cuando tengas TODOS los datos requeridos, pregunta: "¿Estás de acuerdo con estos datos? ¿Procedo a guardar?". SÓLO cuando el usuario confirme, cambia status a "EJECUTADA".
5. DEBES INCLUIR SIEMPRE 'message' en la raíz con lo que le dirás al usuario.
6. NUNCA muestres UUIDs en el texto de tu mensaje, solo nombres limpios.
7. REGLA ESTRICTA DE ESQUEMA: El campo 'type' dentro del objeto 'action' NO SE PUEDE INVENTAR NI COMBINAR. Tienes estrictamente prohibido usar valores que no estén en la lista de JSON de 'ACCIONES PERMITIDAS'. Copia el 'type' letra por letra.
8. En 'parameters', SOLO incluye las llaves (keys) de los datos que el usuario YA te proporcionó. NO pongas valores "null" ni llaves vacías. Si no tienes ningún dato, envía "parameters": {{}}.
9. LA REGLA DE ORO DEL BYPASS Y GUARDADO: Si el usuario te ordena guardar (ej: "sí", "guárdalo", "procede") o te indica que ya llenó los datos manualmente (ej: "ya lo puse", "lo llené yo"), ASUME que todos los datos faltantes ya están en su pantalla. En ese caso, RELLENA cualquier parámetro obligatorio que te falte con el valor 'MANUAL' y CAMBIA INMEDIATAMENTE tu status a 'EJECUTADA'. NUNCA vuelvas a preguntar por datos ni pidas confirmación si el usuario ya te ordenó guardar explícitamente.
"""

        # Inyectar sub-prompt según la ruta
        if intent == "VEHICULOS_PLANES":
            prompt += self._get_vehiculos_prompt(context)
        elif intent == "CITAS":
            prompt += self._get_citas_prompt(context)
        elif intent == "CONFIGURACION":
            prompt += self._get_configuracion_prompt(context)
        elif intent == "PERFIL_USUARIO":
            prompt += self._get_perfil_prompt()
        elif intent == "REPORTES_BITACORA":
            prompt += self._get_reportes_prompt()
        elif intent == "INVENTARIO":
            prompt += self._get_inventario_prompt(context)
        elif intent == "PROVEEDORES":
            prompt += self._get_proveedores_prompt()
        elif intent == "COMPRAS":
            prompt += self._get_compras_prompt()
        elif intent == "USUARIOS":
            prompt += self._get_usuarios_prompt(context)
        elif intent == "BACKUP":
            prompt += self._get_backup_prompt()
        else:
            prompt += self._get_general_prompt()

        return prompt

    def _get_vehiculos_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('owners_list'):
            ctx_str += f"- Propietarios disponibles: {', '.join(context.get('owners_list'))}\n"
        if context and context.get('servicios_list'):
            ctx_str += f"- Servicios del catálogo: {', '.join(context.get('servicios_list'))}\n"

        return f"""
ESTÁS EN EL MÓDULO: VEHICULOS Y PLANES
Contexto Específico:
{ctx_str}

ACCIONES PERMITIDAS (El campo 'type' DEBE ser exactamente uno de los valores listados aquí, y los parameters deben ser un objeto JSON):
```json
[
  {{"type": "BUSCAR_VEHICULO", "parameters": {{"placa": "str", "marca": "str", "modelo": "str"}}}},
  {{"type": "REGISTRAR_VEHICULO", "parameters": {{"placa": "str", "marca": "str", "modelo": "str", "anio": "int", "propietario_id": "str"}}}},
  {{"type": "BUSCAR_PLAN_VEHICULO", "parameters": {{"placa": "str", "estado": "str"}}}},
  {{"type": "VER_PLAN_VEHICULO", "parameters": {{"placa": "str"}}}},
  {{"type": "EDITAR_PLAN_VEHICULO", "parameters": {{"placa": "str", "descripcion_general": "str"}}}},
  {{"type": "CAMBIAR_ESTADO_PLAN_VEHICULO", "parameters": {{"placa": "str", "nuevo_estado": "str", "motivo": "str"}}}},
  {{"type": "AGREGAR_DETALLE_PLAN_VEHICULO", "parameters": {{"placa": "str", "servicio_catalogo_id": "str", "prioridad": "str", "observaciones": "str"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- NO inventes opciones para "marca" o "modelo" porque no hay selector en BD.
- En CAMBIAR_ESTADO_PLAN_VEHICULO, 'nuevo_estado' SOLO puede ser: "LIBRE" o "EN_EJECUCION".
- En AGREGAR_DETALLE_PLAN_VEHICULO, 'prioridad' SOLO puede ser: "Baja", "Media" o "Alta".
- Para modificar la descripción general del plan, TIENES QUE USAR estrictamente `EDITAR_PLAN_VEHICULO`. No intentes crear otra acción.
- Para cambiar el estado del plan, TIENES QUE USAR `CAMBIAR_ESTADO_PLAN_VEHICULO`.
- Si (y SOLO si) el usuario pide modificar UN PLAN DE MANTENIMIENTO genéricamente y no sabes qué acción usar, PREGÚNTALE en texto: "¿Deseas 1) Editar descripción, 2) Cambiar estado, o 3) Agregar detalle?". NO generes el objeto action en ese caso. Cuando el usuario confirme el registro de un vehículo con un "sí", limítate a confirmar que lo vas a guardar y no hagas preguntas de planes.
- MUY IMPORTANTE PARA REGISTRAR_VEHICULO: Nunca te inventes el propietario. Si el usuario te pide registrar un auto, en tu mensaje de texto DEBES mostrarle amigablemente la lista de propietarios disponibles y preguntarle a cuál pertenece.
- Si el usuario elige un Propietario de la lista, extrae su ID (UUID) y envíalo exactamente en el parámetro 'propietario_id'.
"""

    def _get_citas_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        return f"""
ESTÁS EN EL MÓDULO: CITAS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "FILTRAR_CITAS", "parameters": {{"estado": "str", "fecha_desde": "str", "fecha_hasta": "str"}}}},
  {{"type": "CREAR_CITA", "parameters": {{"placa": "str", "fecha": "str", "hora": "str", "observaciones": "str"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- En FILTRAR_CITAS, 'estado' SOLO puede ser: "PROGRAMADA", "PENDIENTE_APROBACION", "EN_ESPERA_INGRESO", "CANCELADA", "NO_SHOW", "FINALIZADA".
"""

    def _get_configuracion_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('espacios_list'):
            ctx_str += f"- Espacios de trabajo: {', '.join(context.get('espacios_list'))}\n"

        return f"""
ESTÁS EN EL MÓDULO: CONFIGURACION (Empresa, Servicios, Horarios y Espacios)
Contexto Específico:
{ctx_str}

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CAMBIAR_NOMBRE_EMPRESA", "parameters": {{"nuevo_nombre": "str"}}}},
  {{"type": "AGREGAR_SERVICIO", "parameters": {{"nombre_servicio": "str", "descripcion": "str", "tiempo_estandar_min": "int", "precio_base": "float"}}}},
  {{"type": "REGISTRAR_ESPACIO", "parameters": {{"nombre": "str", "tipo": "str", "observaciones": "str"}}}},
  {{"type": "EDITAR_ESPACIO", "parameters": {{"espacio_identificador": "str", "nombre": "str", "tipo": "str", "observaciones": "str"}}}},
  {{"type": "VER_HORARIOS_ESPACIO", "parameters": {{"espacio_identificador": "str"}}}},
  {{"type": "AGREGAR_HORARIO_ESPACIO", "parameters": {{"espacio_identificador": "str"}}}},
  {{"type": "EDITAR_HORARIO_ESPACIO", "parameters": {{"espacio_identificador": "str"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- AGREGAR_SERVICIO es para crear un NUEVO tipo de servicio en el Catálogo General del taller (ej: "Cambio de Aceite"). NO es lo mismo que agregar un servicio a un vehículo (eso es AGREGAR_DETALLE_PLAN_VEHICULO).
- Para AGREGAR_SERVICIO, DEBES recopilar: nombre_servicio, descripcion, tiempo_estandar_min (número entero en minutos, múltiplos de 30: 30, 60, 90, 120...), precio_base (número decimal).
- EL CÓDIGO LO GENERA EL SISTEMA automáticamente. No se lo pidas al usuario, ni para servicios ni para espacios.
- NO EXISTE la acción 'REGISTRAR_SERVICIO'. Si necesitas crear un servicio, usa EXACTAMENTE 'AGREGAR_SERVICIO'.
- Para REGISTRAR_ESPACIO, DEBES recopilar: nombre (texto libre), tipo (SOLO puede ser uno de: "TALLER", "CHEQUEO", "GARAJE", "LAVADO"), observaciones (opcional). Muestra las opciones de tipo al usuario como lista.
- En 'parameters' de REGISTRAR_ESPACIO, envía tipo como string en MAYÚSCULAS exactamente: "TALLER", "CHEQUEO", "GARAJE" o "LAVADO".
- Si el usuario habla de espacios existentes, extrae el UUID de la lista inyectada y pásalo en 'espacio_identificador'.
"""

    def _get_perfil_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: PERFIL DEL USUARIO

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CAMBIAR_NOMBRES_PERSONALES", "parameters": {{"nuevo_nombre": "str", "nuevo_apellido": "str"}}}},
  {{"type": "CAMBIAR_TELEFONO", "parameters": {{"nuevo_telefono": "str"}}}},
  {{"type": "CAMBIAR_CONTRASENA", "parameters": {{"contrasena_actual": "str", "nueva_contrasena": "str"}}}},
  {{"type": "ACTUALIZAR_PREFERENCIAS", "parameters": {{"noti_email": "bool", "noti_push": "bool"}}}}
]
```
"""

    def _get_reportes_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: REPORTES Y BITACORA

ACCIONES PERMITIDAS:
```json
[
  {{"type": "FILTRAR_BITACORA", "parameters": {{"search": "str", "accion": "str", "fecha_desde": "str", "fecha_hasta": "str", "orden": "str"}}}},
  {{"type": "EXPORTAR_BITACORA", "parameters": {{"formato": "str"}}}},
  {{"type": "EXPORTAR_REPORTE", "parameters": {{"formato": "str"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- En EXPORTAR_BITACORA y EXPORTAR_REPORTE, el 'formato' SOLO puede ser: "excel" o "pdf".
"""

    def _get_inventario_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('categorias_list'):
            ctx_str += f"- Categorías disponibles: {', '.join(context.get('categorias_list'))}\n"
        
        return f"""
ESTÁS EN EL MÓDULO: INVENTARIO

Contexto Específico:
{ctx_str}

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_CATEGORIA_INVENTARIO", "parameters": {{"nombre": "str", "descripcion": "str"}}}},
  {{"type": "CREAR_ITEM_INVENTARIO", "parameters": {{"categoria_id": "str", "codigo": "str", "nombre": "str", "descripcion": "str", "tipo_item": "str", "unidad_medida": "str", "stock_actual": "int", "stock_minimo": "int", "costo_promedio": "float", "precio_venta": "float"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- En CREAR_ITEM_INVENTARIO, NUNCA inventes la categoría. Extrae el UUID de la categoría si el usuario menciona una de la lista. Si no menciona, muéstrale las categorías disponibles y pregúntale.
- En CREAR_ITEM_INVENTARIO, 'tipo_item' SOLO puede ser: "REPUESTO", "INSUMO" o "PRODUCTO".
- No le pidas el 'código' al usuario, el sistema lo genera automáticamente.
"""

    def _get_proveedores_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: PROVEEDORES

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_PROVEEDOR", "parameters": {{"nombre": "str", "telefono": "str", "email": "str", "direccion": "str", "contacto": "str"}}}}
]
```
"""

    def _get_compras_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: COMPRAS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "AGREGAR_ITEM_COMPRA", "parameters": {{"cantidad": "int", "costo_unitario": "float"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- MUY IMPORTANTE: Cuando el usuario quiera añadir un ítem a la compra, DEBES PREGUNTAR OBLIGATORIAMENTE la cantidad y el costo unitario ANTES de ejecutar la acción.
"""

    def _get_usuarios_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('usuarios_list'):
            ctx_str += f"- Usuarios de la empresa: {', '.join(context.get('usuarios_list'))}\n"
        if context and context.get('roles_list'):
            ctx_str += f"- Roles disponibles: {', '.join(context.get('roles_list'))}\n"
        
        return f"""
ESTÁS EN EL MÓDULO: USUARIOS Y ROLES

Contexto Específico:
{ctx_str}

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_USUARIO", "parameters": {{"nombres": "str", "apellidos": "str", "email": "str", "contrasena": "str", "telefono": "str"}}}},
  {{"type": "CAMBIAR_ROL_USUARIO", "parameters": {{"usuario_id": "str", "nuevo_rol": "str"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- En CAMBIAR_ROL_USUARIO, extrae el UUID del usuario de la lista inyectada y el ID/Nombre del rol de la lista de Roles.
"""

    def _get_backup_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: GESTIÓN DE BACKUPS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CONFIGURAR_BACKUP", "parameters": {{"activo": "bool", "frecuencia": "str", "hora_ejecucion": "str", "compensar_pendientes": "bool"}}}}
]
```

REGLAS ESPECÍFICAS DEL MÓDULO:
- 'frecuencia' SOLO puede ser: "DIARIO", "SEMANAL" o "MENSUAL".
- 'hora_ejecucion' debe ser una hora en formato "HH:MM AM/PM" (ej: "03:00 AM").
"""

    def _get_general_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: GENERAL / CHAT CASUAL

No se detectó una intención clara de modificar un módulo específico. 
Responde amablemente a la consulta del usuario, sugiérele acciones que puede realizar (ej. "Puedo ayudarte a gestionar vehículos, agendar citas o descargar reportes").
No devuelvas ninguna acción técnica ('action') a menos que estés absolutamente seguro.
"""
