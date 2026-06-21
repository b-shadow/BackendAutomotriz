import json
import os
import tempfile
import logging
from rest_framework import viewsets, status, response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

logger = logging.getLogger(__name__)

from modulos.comunicacion_control_inteligencia.models import (
    ConversacionIA,
    MensajeIA,
    AccionIA,
    RolMensajeIA,
    CanalConversacionIA
)
from modulos.comunicacion_control_inteligencia.serializers.ia import (
    ConversacionIASerializer,
    MensajeIASerializer,
    AccionIASerializer
)
from modulos.vehiculos_servicios_plan_citas.models import Vehiculo, ServicioCatalogo, EspacioTrabajo
from modulos.administracion_acceso_configuracion.models import Usuario, Rol
from modulos.inventario_proveedores_administracion.models import CategoriaInventario
from modulos.comunicacion_control_inteligencia.services.ai_service import AIService

class IAViewSet(viewsets.ModelViewSet):
    queryset = ConversacionIA.objects.all()
    serializer_class = ConversacionIASerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Permite filtrar por estado (ej. ?estado=ARCHIVADA para historial). Por defecto devuelve ACTIVA.
        estado = self.request.query_params.get('estado', 'ACTIVA')
        from django.db.models import Count
        
        qs = self.queryset.filter(
            empresa=self.request.user.empresa,
            usuario=self.request.user
        )
        if estado != 'TODAS':
            qs = qs.filter(estado=estado)
            
        return qs.annotate(
            num_mensajes=Count('mensajes')
        ).order_by('-updated_at')

    def perform_create(self, serializer):
        serializer.save(
            empresa=self.request.user.empresa,
            usuario=self.request.user,
            canal=CanalConversacionIA.WEB
        )

    def retrieve(self, request, pk=None, **kwargs):
        """Devuelve una conversación con todos sus mensajes."""
        conversacion = self.get_object()
        mensajes = MensajeIA.objects.filter(conversacion=conversacion).order_by('created_at')
        mensajes_data = [{
            'id': str(m.id),
            'sender': 'user' if m.rol_mensaje == RolMensajeIA.USUARIO else 'ai',
            'text': m.contenido,
            'created_at': m.created_at.isoformat()
        } for m in mensajes]
        conv_data = ConversacionIASerializer(conversacion).data
        conv_data['mensajes'] = mensajes_data
        return response.Response(conv_data)

    @action(detail=True, methods=['post'])
    def archivar(self, request, pk=None, **kwargs):
        """Archiva una conversación (la marca como ARCHIVADA)."""
        conversacion = self.get_object()
        conversacion.estado = 'ARCHIVADA'
        conversacion.save()
        return response.Response({'status': 'success', 'message': 'Conversación archivada correctamente.'})

    @action(detail=True, methods=['post'])
    def enviar_mensaje(self, request, pk=None, **kwargs):
        """
        Envía un mensaje a la IA y recibe una respuesta procesada.
        """
        conversacion = self.get_object()
        contenido = request.data.get('contenido')
        
        if not contenido:
            return response.Response(
                {"error": "El contenido es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 1. Guardar mensaje del usuario
        MensajeIA.objects.create(
            empresa=request.user.empresa,
            conversacion=conversacion,
            rol_mensaje=RolMensajeIA.USUARIO,
            contenido=contenido
        )

        # 2. Obtener historial previo (últimos 6 mensajes para reducir tokens)
        historial = MensajeIA.objects.filter(conversacion=conversacion).order_by('-created_at')[:6]
        mensajes_ia = []
        for msg in reversed(historial):
            role = "user" if msg.rol_mensaje == RolMensajeIA.USUARIO else "assistant"
            mensajes_ia.append({"role": role, "content": msg.contenido})

        # 3. Llamar al servicio de IA
        ai_service = AIService()

        # Pre-detectar intent para inyectar solo el contexto necesario (ahorro de tokens)
        intent_preview = ai_service._route_intent(mensajes_ia)

        # OVERRIDE INTENT: Si hay una acción PENDIENTE, el usuario está llenando un formulario.
        # No debemos dejar que el router adivine mal si el usuario responde algo ambiguo.
        accion_pendiente = AccionIA.objects.filter(
            conversacion=conversacion, 
            usuario=request.user, 
            estado="PENDIENTE"
        ).first()
        
        if accion_pendiente:
            if accion_pendiente.accion in ["REGISTRAR_VEHICULO", "BUSCAR_VEHICULO", "BUSCAR_PLAN_VEHICULO", "VER_PLAN_VEHICULO", "EDITAR_PLAN_VEHICULO", "CAMBIAR_ESTADO_PLAN_VEHICULO", "AGREGAR_DETALLE_PLAN_VEHICULO"]:
                intent_preview = "VEHICULOS_PLANES"
            elif accion_pendiente.accion in ["CREAR_CITA", "FILTRAR_CITAS"]:
                intent_preview = "CITAS"
            elif accion_pendiente.accion in ["AGREGAR_SERVICIO", "REGISTRAR_ESPACIO", "EDITAR_ESPACIO", "VER_HORARIOS_ESPACIO", "AGREGAR_HORARIO_ESPACIO", "EDITAR_HORARIO_ESPACIO", "CAMBIAR_NOMBRE_EMPRESA"]:
                intent_preview = "CONFIGURACION"
            elif accion_pendiente.accion in ["CAMBIAR_NOMBRES_PERSONALES", "CAMBIAR_TELEFONO", "CAMBIAR_CONTRASENA", "ACTUALIZAR_PREFERENCIAS"]:
                intent_preview = "PERFIL_USUARIO"
            elif accion_pendiente.accion in ["FILTRAR_BITACORA", "EXPORTAR_BITACORA", "VER_REPORTE_GLOBAL", "VER_REPORTE_VEHICULO", "VER_REPORTE_PRESUPUESTO", "VER_REPORTE_INVENTARIO", "EXPORTAR_REPORTE"]:
                intent_preview = "REPORTES_BITACORA"
            elif accion_pendiente.accion in ["CREAR_CATEGORIA_INVENTARIO", "CREAR_ITEM_INVENTARIO"]:
                intent_preview = "INVENTARIO"
            elif accion_pendiente.accion in ["CREAR_PROVEEDOR"]:
                intent_preview = "PROVEEDORES"
            elif accion_pendiente.accion in ["AGREGAR_ITEM_COMPRA"]:
                intent_preview = "COMPRAS"
            elif accion_pendiente.accion in ["CREAR_USUARIO", "CAMBIAR_ROL_USUARIO"]:
                intent_preview = "USUARIOS"
            elif accion_pendiente.accion in ["CONFIGURAR_BACKUP"]:
                intent_preview = "BACKUP"

        owners_list = []
        servicios_list = []
        espacios_list = []
        categorias_list = []
        usuarios_list = []
        roles_list = []

        if intent_preview in ("VEHICULOS_PLANES",):
            propietarios = Usuario.objects.filter(empresa=request.user.empresa).values('id', 'nombres', 'apellidos')
            owners_list = [f"{p['nombres']} {p['apellidos']} (ID: {p['id']})" for p in propietarios]

        if intent_preview in ("VEHICULOS_PLANES", "CONFIGURACION"):
            servicios = ServicioCatalogo.objects.filter(empresa=request.user.empresa, activo=True).values('id', 'nombre')
            servicios_list = [f"{s['nombre']} (UUID={s['id']})" for s in servicios]

        if intent_preview in ("CONFIGURACION",):
            espacios = EspacioTrabajo.objects.filter(empresa=request.user.empresa, activo=True).values('id', 'nombre', 'codigo')
            espacios_list = [f"{e['nombre']} [{e['codigo']}] (ID: {e['id']})" for e in espacios]

        if intent_preview in ("INVENTARIO",):
            categorias = CategoriaInventario.objects.filter(empresa=request.user.empresa, activo=True).values('id', 'nombre')
            categorias_list = [f"{c['nombre']} (ID: {c['id']})" for c in categorias]

        if intent_preview in ("USUARIOS",):
            usuarios = Usuario.objects.filter(empresa=request.user.empresa, is_active=True).values('id', 'nombres', 'apellidos')
            usuarios_list = [f"{u['nombres']} {u['apellidos']} (ID: {u['id']})" for u in usuarios]
            roles = Rol.objects.all().values('id', 'nombre')
            roles_list = [f"{r['nombre']} (ID: {r['id']})" for r in roles]

        contexto = {
            "tenant_name": request.user.empresa.nombre,
            "user_name": f"{request.user.nombres} {request.user.apellidos}",
            "user_role": request.user.rol.nombre if request.user.rol else "Sin Rol",
            "owners_list": owners_list,
            "servicios_list": servicios_list,
            "espacios_list": espacios_list,
            "categorias_list": categorias_list,
            "usuarios_list": usuarios_list,
            "roles_list": roles_list,
            "current_form_data": accion_pendiente.parametros if accion_pendiente else {}
        }
        
        ai_res = ai_service.get_chat_response(mensajes_ia, user_context=contexto)
        
        # 4. Procesar respuesta de la IA (Objeto Pydantic)
        ai_data = ai_res.model_dump()

        # 5. Guardar mensaje de la IA
        MensajeIA.objects.create(
            empresa=request.user.empresa,
            conversacion=conversacion,
            rol_mensaje=RolMensajeIA.ASISTENTE,
            contenido=ai_data.get("message", ""),
            metadata={"raw_response": ai_data}
        )

        # 6. Si hay una acción sugerida, registrarla o actualizarla en la BD (Máquina de Estados)
        accion_obj = None
        if ai_data.get("action"):
            action_data = ai_data.get("action")
            nuevo_estado = action_data.get("status", "PENDIENTE")
            accion_tipo = action_data.get("type")
            params = action_data.get("parameters", {})

            # Buscar si ya existe una acción PENDIENTE de este tipo en la conversación
            accion_existente = AccionIA.objects.filter(
                conversacion=conversacion,
                usuario=request.user,
                accion=accion_tipo,
                estado="PENDIENTE"
            ).first()

            if accion_existente:
                # Actualizar acción existente (Merge de parámetros para evitar amnesia de la IA)
                merged_params = {**accion_existente.parametros, **params}
                accion_existente.parametros = merged_params
                accion_existente.estado = nuevo_estado
                accion_existente.requiere_confirmacion = (nuevo_estado == "PENDIENTE")
                accion_existente.save()
                accion_obj = accion_existente
            else:
                # Crear nueva acción
                accion_obj = AccionIA.objects.create(
                    empresa=request.user.empresa,
                    conversacion=conversacion,
                    usuario=request.user,
                    accion=accion_tipo,
                    parametros=params,
                    estado=nuevo_estado,
                    requiere_confirmacion=(nuevo_estado == "PENDIENTE")
                )

            # Si la IA determina que ya debe ejecutarse (por confirmación en chat)
            if accion_obj.estado == "EJECUTADA":
                self._ejecutar_logica_accion(accion_obj, request.user)

        return response.Response({
            "mensaje_ia": ai_data.get("message"),
            "accion": AccionIASerializer(accion_obj).data if accion_obj else None,
            "suggested_actions": ai_data.get("suggested_actions", []),
            "options": ai_data.get("options", []),
            "ui_type": ai_data.get("ui_type"),
            "current_conversation_id": conversacion.id
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def transcribir(self, request, **kwargs):
        """
        Endpoint para transcribir audio a texto.
        """
        audio_file = request.FILES.get('audio')
        if not audio_file:
            return response.Response(
                {"error": "Archivo de audio es requerido"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Procesar con la extensión correcta
        import os
        import traceback
        ext = os.path.splitext(audio_file.name)[1] or '.webm'
        
        # Guardar logs en un archivo de debug
        debug_log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'transcribe_debug.log')
        
        with open(debug_log_path, 'a', encoding='utf-8') as log_f:
            log_f.write(f"\n--- Nueva Transcripción ---\n")
            log_f.write(f"Nombre de archivo: {audio_file.name}\n")
            log_f.write(f"Tamaño: {audio_file.size} bytes\n")
            log_f.write(f"Content Type: {audio_file.content_type}\n")
            log_f.write(f"Extensión detectada: {ext}\n")

        try:
            ai_service = AIService()
            texto = ai_service.transcribe_audio(audio_file)
            
            with open(debug_log_path, 'a', encoding='utf-8') as log_f:
                log_f.write(f"Resultado de Whisper: '{texto}'\n")
            
            # Limpiar alucinaciones típicas de Whisper en silencio/ruido
            if texto:
                texto_limpio = texto.strip().lower().replace(".", "").replace("!", "").replace("¿", "").replace("?", "").replace(",", "")
                # Remover acentos/diacríticos para una comparación limpia
                import unicodedata
                texto_limpio = "".join(c for c in unicodedata.normalize('NFD', texto_limpio) if unicodedata.category(c) != 'Mn')
                
                hallucinaciones = [
                    "gracias", "gracias por ver", "subtitulos por la comunidad de amaraorg", 
                    "subtitulos por", "comunidad de amaraorg", "amaraorg", "descargado de", 
                    "y ya", "uh", "eh", "oh", "subtitulos", "por ver", "hun er ad hun their i valmeton",
                    "hún er að hún þeir í valmetón", "subtitulos hechos por la comunidad de amaraorg"
                ]
                if texto_limpio in hallucinaciones or len(texto_limpio.strip()) <= 2 or "valmetón" in texto_limpio or "amaraorg" in texto_limpio:
                    with open(debug_log_path, 'a', encoding='utf-8') as log_f:
                        log_f.write(f"Texto clasificado como alucinación ('{texto_limpio}'), vaciando\n")
                    texto = ""
                    
            return response.Response({"texto": texto})
        except Exception as e:
            tb = traceback.format_exc()
            with open(debug_log_path, 'a', encoding='utf-8') as log_f:
                log_f.write(f"ERROR: {str(e)}\nTraceback:\n{tb}\n")
            return response.Response({"texto": "", "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _ejecutar_logica_accion(self, accion, user):
        """
        Lógica centralizada para ejecutar acciones de negocio.
        """
        logger.info(f"Ejecutando lógica de acción IA: {accion.accion} para usuario {user.id}")
        
        if accion.accion in [
            "CAMBIAR_NOMBRES_PERSONALES", "CAMBIAR_TELEFONO", "CAMBIAR_CONTRASENA", 
            "ACTUALIZAR_PREFERENCIAS", "CAMBIAR_NOMBRE_EMPRESA",
            "COMPRAR_PLAN", "RELLENAR_PAGO", "CANCELAR_CAMBIO"
        ]:
            # Estas acciones son para el frontend (llenado visual mediante Ghost Automation)
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": "Formulario rellenado correctamente. Por favor revisa y confirma manualmente."}

        elif accion.accion == "REGISTRAR_VEHICULO":
            # La creación real del vehículo la hace el frontend (VehiculoModal)
            # mediante Ghost Simulation cuando recibe el status EJECUTADA.
            # Aquí solo validamos y marcamos la acción como lista.
            placa = accion.parametros.get("placa")
            marca = accion.parametros.get("marca")
            modelo = accion.parametros.get("modelo")
            anio = accion.parametros.get("anio")
            
            if placa and marca and modelo and anio:
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": f"Formulario listo para registrar vehículo con placa {placa}. Confirma visualmente."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Faltan parámetros obligatorios (placa, marca, modelo, año)"}

        elif accion.accion == "AGREGAR_SERVICIO":
            nombre = accion.parametros.get("nombre_servicio")
            descripcion = accion.parametros.get("descripcion")
            tiempo = accion.parametros.get("tiempo_estandar_min")
            precio = accion.parametros.get("precio_base")

            if nombre and descripcion and tiempo and precio:
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": f"Formulario listo para agregar servicio {nombre}."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Faltan parámetros obligatorios para el servicio"}

        elif accion.accion == "REGISTRAR_ESPACIO":
            codigo = accion.parametros.get("codigo")
            nombre = accion.parametros.get("nombre")
            tipo = accion.parametros.get("tipo")

            if codigo and nombre and tipo:
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": f"Formulario listo para registrar espacio {nombre}."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Faltan parámetros obligatorios para el espacio"}

        elif accion.accion in ["EDITAR_ESPACIO", "VER_HORARIOS_ESPACIO", "AGREGAR_HORARIO_ESPACIO", "EDITAR_HORARIO_ESPACIO"]:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción {accion.accion} delegada al frontend."}
        
        elif accion.accion == "CREAR_CITA":
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": "Cita agendada correctamente (Simulado)."}

        elif accion.accion == "BUSCAR_VEHICULO":
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": "Búsqueda de vehículo delegada al frontend."}

        elif accion.accion == "FILTRAR_CITAS":
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": "Filtrado de citas delegado al frontend."}

        elif accion.accion in ["BUSCAR_PLAN_VEHICULO", "VER_PLAN_VEHICULO", "EDITAR_PLAN_VEHICULO", "CAMBIAR_ESTADO_PLAN_VEHICULO", "AGREGAR_DETALLE_PLAN_VEHICULO"]:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción de plan de vehículo {accion.accion} delegada al frontend."}
            
        elif accion.accion in ["FILTRAR_BITACORA", "EXPORTAR_BITACORA"]:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción de bitácora {accion.accion} delegada al frontend."}
            
        elif accion.accion in ["VER_REPORTE_GLOBAL", "VER_REPORTE_VEHICULO", "VER_REPORTE_PRESUPUESTO", "VER_REPORTE_INVENTARIO", "EXPORTAR_REPORTE"]:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción de reportes {accion.accion} delegada al frontend."}
        
        else:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción {accion.accion} completada con éxito"}
        
        accion.save()

    @action(detail=True, methods=['post'])
    def confirmar_accion(self, request, pk=None, **kwargs):
        """
        Confirma y ejecuta una acción de la IA vía botón (Legacy/Fallback).
        """
        accion_id = request.data.get('accion_id')
        try:
            accion = AccionIA.objects.get(id=accion_id, usuario=request.user)
            self._ejecutar_logica_accion(accion, request.user)
            return response.Response(AccionIASerializer(accion).data)
        except AccionIA.DoesNotExist:
            return response.Response({"error": "Acción no encontrada"}, status=status.HTTP_404_NOT_FOUND)
            return response.Response(
                {"error": "Acción no encontrada"},
                status=status.HTTP_404_NOT_FOUND
            )
