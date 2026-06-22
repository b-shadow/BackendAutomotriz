import os
from typing import List, Dict, Any, Optional
from groq import Groq
from django.conf import settings
import instructor
from .schemas import IAAssistantResponse, IntentClassification

class AIService:
    """
    Servicio para interactuar con la API de Groq usando Instructor para validaciÃ³n Pydantic.
    Implementa el patrÃ³n Router-Agente para optimizar tokens y modularizar reglas.
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        # Modelo ligero exclusivo para el enrutador (solo clasifica en 6 categorÃ­as)
        self.router_model = os.getenv("GROQ_ROUTER_MODEL", "llama-3.1-8b-instant")
        self.transcription_model = os.getenv("GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3")
        
        if not self.api_key:
            raise ValueError("GROQ_API_KEY no estÃ¡ configurada en las variables de entorno.")
            
        self.raw_client = Groq(api_key=self.api_key)
        self.client = instructor.from_groq(self.raw_client)

    def _route_intent(self, messages: List[Dict[str, str]]) -> str:
        """
        Fase 1: Enrutador rÃ¡pido para detectar el mÃ³dulo del cual estÃ¡ hablando el usuario.
        Usa los Ãºltimos 3 intercambios para evitar confusiÃ³n por contexto previo.
        """
        if not messages:
            return "GENERAL"

        # Tomar los Ãºltimos 3 mensajes para dar contexto al router
        recent = messages[-4:] if len(messages) >= 4 else messages
        context_lines = []
        for msg in recent:
            role_label = "Usuario" if msg['role'] == 'user' else "Asistente"
            context_lines.append(f"{role_label}: {msg['content'][:200]}")
        context_str = "\n".join(context_lines)

        router_prompt = f"""Clasifica el ÃšLTIMO mensaje del usuario en uno de estos mÃ³dulos de un SaaS de Taller MecÃ¡nico.
  IMPORTANTE: Clasifica como CONFIGURACION (catÃ¡logo de servicios) SOLO si el usuario dice literalmente "servicio", "horario", "espacio" o "nombre de empresa".
  IMPORTANTE: Palabras como "item", "Ã­tem", "unitem", "repuesto", "insumo", "producto", "pieza", "tornillo", "llanta", o menciones a "inventario" y "stock" -> INVENTARIO. NUNCA lo mandes a CONFIGURACION.
  Clasifica como VEHICULOS_PLANES si se habla explÃ­citamente de autos, placas, propietarios, dueÃ±os, o planes de mantenimiento de un vehÃ­culo.
  
  MÃ³dulos:
  - VEHICULOS_PLANES: Registrar autos, buscar por placa, ver/elegir propietarios, planes de mantenimiento de vehÃ­culo especÃ­fico.
  - CITAS: Agendar, filtrar o buscar citas de taller.
  - CONFIGURACION: Crear/editar servicios del catÃ¡logo del taller, horarios, espacios de trabajo, nombre de empresa.
  - PERFIL_USUARIO: Nombres, telÃ©fonos, contraseÃ±as, preferencias del usuario.
  - REPORTES_BITACORA: BitÃ¡coras, reportes PDF/Excel, logs de actividad, filtrar bitÃ¡cora.
  - INVENTARIO: Registrar categorÃ­as, crear Ã­tems de inventario (repuestos, insumos, productos), stock.
- PROVEEDORES: AÃ±adir proveedores de la empresa.
- COMPRAS: Compras de insumos o repuestos.
- USUARIOS: GestiÃ³n de usuarios del sistema, aÃ±adir usuario, cambiar roles.
- BACKUP: Configuraciones de copias de seguridad de la base de datos.
- FINANZAS_VENTAS: Ventas presenciales en mostrador, emisiÃ³n de facturas o recibos, consulta de caja y movimientos financieros.
- GENERAL: Saludos, preguntas generales, sin acciÃ³n especÃ­fica.

ConversaciÃ³n reciente:
{context_str}

Responde SOLO con el mÃ³dulo correspondiente."""

        try:
            # Router usa modelo ligero 8B â€” solo clasifica en 6 categorÃ­as
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
        Fase 2: Obtiene una respuesta de chat estructurada inyectando solo el prompt del mÃ³dulo.
        Incluye reintentos manuales con mensaje de correcciÃ³n si el LLM usa un 'type' invÃ¡lido.
        """
        intent = self._route_intent(messages)
        print(f"[AI Router] IntenciÃ³n detectada: {intent}")

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

                # Si el error es de validaciÃ³n de tipo (LLM inventÃ³ una acciÃ³n), inyectar correcciÃ³n
                if "tool call validation failed" in error_str or "value must be one of" in error_str:
                    if attempt < MAX_ATTEMPTS - 1:
                        correction_msg = (
                            "CORRECCIÃ“N OBLIGATORIA: Tu respuesta anterior fue rechazada porque usaste "
                            "un 'type' de acciÃ³n que NO EXISTE en el esquema. "
                            "Revisa la lista de ACCIONES PERMITIDAS y usa EXACTAMENTE uno de esos valores sin modificarlo. "
                            "Por ejemplo: para crear un servicio en el catÃ¡logo usa 'AGREGAR_SERVICIO', nunca 'REGISTRAR_SERVICIO'. "
                            "Responde de nuevo con el 'type' correcto."
                        )
                        full_messages = full_messages + [{"role": "user", "content": correction_msg}]
                        continue
                # Cualquier otro error: salir del bucle
                break

        print(f"Error en AIService.get_chat_response: {str(last_error)}")
        return IAAssistantResponse(
            message="Lo siento, he tenido un problema tÃ©cnico al procesar tu solicitud. Por favor, intÃ©ntalo de nuevo en un momento.",
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
                prompt="Por favor, transcribe este audio en espaÃ±ol. Ignora ruidos estÃ¡ticos.",
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
            base_context = f"Empresa: {context.get('tenant_name')}\nUsuario: {context.get('user_name')} ({context.get('user_role')})\nDATOS DEL FORMULARIO YA RECOLECTADOS Y GUARDADOS: {form_data_str} (Â¡NO VUELVAS A PREGUNTAR AL USUARIO POR ESTOS DATOS, YA LOS TIENES!)"
        else:
            base_context = ""
        
        # Reglas de Oro Generales
        prompt = f"""
Eres AutoTaller AI, el asistente inteligente para un software SaaS de talleres mecÃ¡nicos.
Contexto Base:
{base_context}

REGLAS GENERALES ESTRICTAS:
  1. Tu Ãºnico propÃ³sito es ayudar al usuario a usar el sistema. Si te preguntan cosas ajenas, di que solo ayudas con el taller.
  2. NUNCA inventes IDs, placas o datos. Si el usuario ya te dio un dato, NO LO VUELVAS A PREGUNTAR.
  3. OBLIGATORIO: DEBES generar SIEMPRE el objeto 'action' con status="PENDIENTE" desde tu primer mensaje para abrir el formulario al usuario e ir pre-llenando los datos, incluso si no tienes ningÃºn parÃ¡metro todavÃ­a. NUNCA respondas sin el objeto 'action' si el usuario pide realizar una acciÃ³n.
  4. Cuando tengas TODOS los datos requeridos, pregunta: "Â¿EstÃ¡s de acuerdo con estos datos? Â¿Procedo a guardar?". SÃ“LO cuando el usuario confirme, cambia status a "EJECUTADA".
5. DEBES INCLUIR SIEMPRE 'message' en la raÃ­z con lo que le dirÃ¡s al usuario.
6. NUNCA muestres UUIDs en el texto de tu mensaje, solo nombres limpios.
7. REGLA ESTRICTA DE ESQUEMA: El campo 'type' dentro del objeto 'action' NO SE PUEDE INVENTAR NI COMBINAR. Tienes estrictamente prohibido usar valores que no estÃ©n en la lista de JSON de 'ACCIONES PERMITIDAS'. Copia el 'type' letra por letra.
8. En 'parameters', SOLO incluye las llaves (keys) de los datos que el usuario YA te proporcionÃ³. NO pongas valores "null" ni llaves vacÃ­as. Si no tienes ningÃºn dato, envÃ­a "parameters": {{}}.
9. LA REGLA DE ORO DEL BYPASS Y GUARDADO: Si el usuario te ordena guardar (ej: "sÃ­", "guÃ¡rdalo", "procede") o te indica que ya llenÃ³ los datos manualmente (ej: "ya lo puse", "lo llenÃ© yo"), ASUME que todos los datos faltantes ya estÃ¡n en su pantalla. En ese caso, RELLENA cualquier parÃ¡metro obligatorio que te falte con el valor 'MANUAL' y CAMBIA INMEDIATAMENTE tu status a 'EJECUTADA'. NUNCA vuelvas a preguntar por datos ni pidas confirmaciÃ³n si el usuario ya te ordenÃ³ guardar explÃ­citamente.
"""

        # Inyectar sub-prompt segÃºn la ruta
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
        elif intent == "FINANZAS_VENTAS":
            prompt += self._get_finanzas_ventas_prompt()
        else:
            prompt += self._get_general_prompt()

        return prompt

    def _get_vehiculos_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('owners_list'):
            ctx_str += f"- Propietarios disponibles: {', '.join(context.get('owners_list'))}\n"
        if context and context.get('servicios_list'):
            ctx_str += f"- Servicios del catÃ¡logo: {', '.join(context.get('servicios_list'))}\n"

        return f"""
ESTÃ�S EN EL MÃ“DULO: VEHICULOS Y PLANES
Contexto EspecÃ­fico:
{ctx_str}

ACCIONES PERMITIDAS (El campo 'type' DEBE ser exactamente uno de los valores listados aquÃ­, y los parameters deben ser un objeto JSON):
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

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- NO inventes opciones para "marca" o "modelo" porque no hay selector en BD.
- En CAMBIAR_ESTADO_PLAN_VEHICULO, 'nuevo_estado' SOLO puede ser: "LIBRE" o "EN_EJECUCION".
- En AGREGAR_DETALLE_PLAN_VEHICULO, 'prioridad' SOLO puede ser: "Baja", "Media" o "Alta".
- Para modificar la descripciÃ³n general del plan, TIENES QUE USAR estrictamente `EDITAR_PLAN_VEHICULO`. No intentes crear otra acciÃ³n.
- Para cambiar el estado del plan, TIENES QUE USAR `CAMBIAR_ESTADO_PLAN_VEHICULO`.
- Si (y SOLO si) el usuario pide modificar UN PLAN DE MANTENIMIENTO genÃ©ricamente y no sabes quÃ© acciÃ³n usar, PREGÃšNTALE en texto: "Â¿Deseas 1) Editar descripciÃ³n, 2) Cambiar estado, o 3) Agregar detalle?". NO generes el objeto action en ese caso. Cuando el usuario confirme el registro de un vehÃ­culo con un "sÃ­", limÃ­tate a confirmar que lo vas a guardar y no hagas preguntas de planes.
- MUY IMPORTANTE PARA REGISTRAR_VEHICULO: Nunca te inventes el propietario. Si el usuario te pide registrar un auto, en tu mensaje de texto DEBES mostrarle amigablemente la lista de propietarios disponibles y preguntarle a cuÃ¡l pertenece.
- Si el usuario elige un Propietario de la lista, extrae su ID (UUID) y envÃ­alo exactamente en el parÃ¡metro 'propietario_id'.
"""

    def _get_citas_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: CITAS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "FILTRAR_CITAS", "parameters": {{"estado": "str", "fecha_desde": "str", "fecha_hasta": "str"}}}},
  {{"type": "CREAR_CITA", "parameters": {{"placa": "str", "fecha": "str", "hora": "str", "observaciones": "str"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- En FILTRAR_CITAS, 'estado' SOLO puede ser: "PROGRAMADA", "PENDIENTE_APROBACION", "EN_ESPERA_INGRESO", "CANCELADA", "NO_SHOW", "FINALIZADA".
"""

    def _get_configuracion_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('espacios_list'):
            ctx_str += f"- Espacios de trabajo: {', '.join(context.get('espacios_list'))}\n"

        return f"""
ESTÃ�S EN EL MÃ“DULO: CONFIGURACION (Empresa, Servicios, Horarios y Espacios)
Contexto EspecÃ­fico:
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

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- AGREGAR_SERVICIO es para crear un NUEVO tipo de servicio en el CatÃ¡logo General del taller (ej: "Cambio de Aceite"). NO es lo mismo que agregar un servicio a un vehÃ­culo (eso es AGREGAR_DETALLE_PLAN_VEHICULO).
- Para AGREGAR_SERVICIO, DEBES recopilar: nombre_servicio, descripcion, tiempo_estandar_min (nÃºmero entero en minutos, mÃºltiplos de 30: 30, 60, 90, 120...), precio_base (nÃºmero decimal).
- EL CÃ“DIGO LO GENERA EL SISTEMA automÃ¡ticamente. No se lo pidas al usuario, ni para servicios ni para espacios.
- NO EXISTE la acciÃ³n 'REGISTRAR_SERVICIO'. Si necesitas crear un servicio, usa EXACTAMENTE 'AGREGAR_SERVICIO'.
- Para REGISTRAR_ESPACIO, DEBES recopilar: nombre (texto libre), tipo (SOLO puede ser uno de: "TALLER", "CHEQUEO", "GARAJE", "LAVADO"), observaciones (opcional). Muestra las opciones de tipo al usuario como lista.
- En 'parameters' de REGISTRAR_ESPACIO, envÃ­a tipo como string en MAYÃšSCULAS exactamente: "TALLER", "CHEQUEO", "GARAJE" o "LAVADO".
- Si el usuario habla de espacios existentes, extrae el UUID de la lista inyectada y pÃ¡salo en 'espacio_identificador'.
"""

    def _get_perfil_prompt(self) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: PERFIL DEL USUARIO

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
ESTÃ�S EN EL MÃ“DULO: REPORTES Y BITACORA

ACCIONES PERMITIDAS:
```json
[
  {{"type": "FILTRAR_BITACORA", "parameters": {{"search": "str", "accion": "str", "fecha_desde": "str", "fecha_hasta": "str", "orden": "str"}}}},
  {{"type": "EXPORTAR_BITACORA", "parameters": {{"formato": "str"}}}},
  {{"type": "EXPORTAR_REPORTE", "parameters": {{"formato": "str"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- En EXPORTAR_BITACORA y EXPORTAR_REPORTE, el 'formato' SOLO puede ser: "excel" o "pdf".
"""

    def _get_inventario_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('categorias_list'):
            ctx_str += f"- CategorÃ­as disponibles: {', '.join(context.get('categorias_list'))}\n"
        
        return f"""
ESTÃ�S EN EL MÃ“DULO: INVENTARIO

Contexto EspecÃ­fico:
{ctx_str}

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_CATEGORIA_INVENTARIO", "parameters": {{"nombre": "str", "descripcion": "str"}}}},
  {{"type": "CREAR_ITEM_INVENTARIO", "parameters": {{"categoria_id": "str", "codigo": "str", "nombre": "str", "descripcion": "str", "tipo_item": "str", "unidad_medida": "str", "stock_actual": "int", "stock_minimo": "int", "costo_promedio": "float", "precio_venta": "float"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- En CREAR_ITEM_INVENTARIO, NUNCA inventes la categorÃ­a. Extrae el UUID de la categorÃ­a si el usuario menciona una de la lista. Si no menciona, muÃ©strale las categorÃ­as disponibles y pregÃºntale.
- En CREAR_ITEM_INVENTARIO, 'tipo_item' SOLO puede ser: "REPUESTO", "INSUMO" o "PRODUCTO".
- No le pidas el 'cÃ³digo' al usuario, el sistema lo genera automÃ¡ticamente.
"""

    def _get_proveedores_prompt(self) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: PROVEEDORES

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_PROVEEDOR", "parameters": {{"nombre": "str", "telefono": "str", "email": "str", "direccion": "str", "contacto": "str"}}}}
]
```
"""

    def _get_compras_prompt(self) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: COMPRAS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "AGREGAR_ITEM_COMPRA", "parameters": {{"cantidad": "int", "costo_unitario": "float"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- MUY IMPORTANTE: Cuando el usuario quiera aÃ±adir un Ã­tem a la compra, DEBES PREGUNTAR OBLIGATORIAMENTE la cantidad y el costo unitario ANTES de ejecutar la acciÃ³n.
"""

    def _get_usuarios_prompt(self, context: Optional[Dict[str, Any]]) -> str:
        ctx_str = ""
        if context and context.get('usuarios_list'):
            ctx_str += f"- Usuarios de la empresa: {', '.join(context.get('usuarios_list'))}\n"
        if context and context.get('roles_list'):
            ctx_str += f"- Roles disponibles: {', '.join(context.get('roles_list'))}\n"
        
        return f"""
ESTÃ�S EN EL MÃ“DULO: USUARIOS Y ROLES

Contexto EspecÃ­fico:
{ctx_str}

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CREAR_USUARIO", "parameters": {{"nombres": "str", "apellidos": "str", "email": "str", "contrasena": "str", "telefono": "str"}}}},
  {{"type": "CAMBIAR_ROL_USUARIO", "parameters": {{"usuario_id": "str", "nuevo_rol": "str"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- En CAMBIAR_ROL_USUARIO, extrae el UUID del usuario de la lista inyectada y el ID/Nombre del rol de la lista de Roles.
"""

    def _get_backup_prompt(self) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: GESTIÃ“N DE BACKUPS

ACCIONES PERMITIDAS:
```json
[
  {{"type": "CONFIGURAR_BACKUP", "parameters": {{"activo": "bool", "frecuencia": "str", "hora_ejecucion": "str", "compensar_pendientes": "bool"}}}}
]
```

REGLAS ESPECÃ�FICAS DEL MÃ“DULO:
- 'frecuencia' SOLO puede ser: "DIARIO", "SEMANAL" o "MENSUAL".
- 'hora_ejecucion' debe ser una hora en formato "HH:MM AM/PM" (ej: "03:00 AM").
"""

    def _get_general_prompt(self) -> str:
        return f"""
ESTÃ�S EN EL MÃ“DULO: GENERAL / CHAT CASUAL

No se detectÃ³ una intenciÃ³n clara de modificar un mÃ³dulo especÃ­fico. 
Responde amablemente a la consulta del usuario, sugiÃ©rele acciones que puede realizar (ej. "Puedo ayudarte a gestionar vehÃ­culos, agendar citas o descargar reportes").
No devuelvas ninguna acciÃ³n tÃ©cnica ('action') a menos que estÃ©s absolutamente seguro.
"""

    def _get_finanzas_ventas_prompt(self) -> str:
        return f"""
ESTÁS EN EL MÓDULO: FINANZAS Y VENTAS

Aquí puedes registrar ventas presenciales de mostrador, emitir facturas/recibos a partir de pagos, y consultar el estado de la caja registradora.

ACCIONES PERMITIDAS Y SUS PARÁMETROS:

1. AGREGAR_ITEM_VENTA: Úsala para agregar un producto al carrito de venta presencial en mostrador.
   Parámetros:
   - "itemId": Nombre o código del ítem a agregar.
   - "cantidad": Cantidad a vender.

2. EMITIR_FACTURA: Úsala para emitir una factura o recibo.
   Parámetros:
   - "pago_taller": El pago asociado a esta factura.
   - "numero": (Opcional) Número del comprobante.
   - "nit_razon_social": NIT o Razón social del cliente a facturar.

3. CONSULTAR_CAJA: Úsala cuando el usuario quiera saber el saldo actual, ingresos o egresos de su caja activa. (Solo informa, no requiere parámetros específicos).

IMPORTANTE:
- Cuando el usuario indique una acción, si faltan parámetros, envía la acción con status="PENDIENTE" y los campos que conozcas, llenando con "MANUAL" los faltantes.
- En el campo 'message', pide amigablemente los parámetros que faltan.
- Si el usuario ha dado todos los parámetros, envía la acción con status="PENDIENTE" y pregunta si desea proceder/guardar.
- Solo envía status="EJECUTADA" cuando el usuario haya dicho "sí", "guardar", "procede" después de ver todos los datos.
"""
