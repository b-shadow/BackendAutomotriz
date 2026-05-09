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
from modulos.vehiculos_servicios_plan_citas.models import Vehiculo
from modulos.administracion_acceso_configuracion.models import Usuario
from modulos.comunicacion_control_inteligencia.services.ai_service import AIService

class IAViewSet(viewsets.ModelViewSet):
    queryset = ConversacionIA.objects.all()
    serializer_class = ConversacionIASerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Solo conversaciones ACTIVAS del usuario, priorizando las que tienen mensajes
        from django.db.models import Count
        return self.queryset.filter(
            empresa=self.request.user.empresa,
            usuario=self.request.user,
            estado='ACTIVA'
        ).annotate(
            num_mensajes=Count('mensajes')
        ).order_by('-num_mensajes', '-updated_at')

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

        # 2. Obtener historial previo para contexto (últimos 10 mensajes)
        historial = MensajeIA.objects.filter(conversacion=conversacion).order_by('-created_at')[:10]
        mensajes_ia = []
        for msg in reversed(historial):
            role = "user" if msg.rol_mensaje == RolMensajeIA.USUARIO else "assistant"
            mensajes_ia.append({"role": role, "content": msg.contenido})

        # 3. Llamar al servicio de IA
        ai_service = AIService()
        # Obtener lista de usuarios (posibles propietarios)
        propietarios = Usuario.objects.filter(empresa=request.user.empresa).values('id', 'nombres', 'apellidos', 'email')
        owners_list = [f"{p['nombres']} {p['apellidos']} (ID: {p['id']}) - {p['email']}" for p in propietarios]

        contexto = {
            "tenant_name": request.user.empresa.nombre,
            "user_name": f"{request.user.nombres} {request.user.apellidos}",
            "user_role": request.user.rol.nombre if request.user.rol else "Sin Rol",
            "owners_list": owners_list
        }
        
        ai_res = ai_service.get_chat_response(mensajes_ia, user_context=contexto)
        
        # 4. Procesar respuesta de la IA (JSON)
        ai_content = ai_res.get("content", "{}")
        try:
            ai_data = json.loads(ai_content)
        except:
            ai_data = {
                "message": ai_content,
                "action": None,
                "suggested_actions": []
            }

        # 5. Guardar mensaje de la IA
        MensajeIA.objects.create(
            empresa=request.user.empresa,
            conversacion=conversacion,
            rol_mensaje=RolMensajeIA.ASISTENTE,
            contenido=ai_data.get("message", ""),
            metadata={"raw_response": ai_data}
        )

        # 6. Si hay una acción sugerida, registrarla en la BD
        accion_obj = None
        if ai_data.get("action"):
            action_data = ai_data.get("action")
            # Extraer parámetros e incluir redirect_path si existe
            params = action_data.get("parameters", {})
            if action_data.get("redirect_path"):
                params["_redirect_path"] = action_data.get("redirect_path")

            accion_obj = AccionIA.objects.create(
                empresa=request.user.empresa,
                conversacion=conversacion,
                usuario=request.user,
                accion=action_data.get("type"),
                parametros=params,
                estado=action_data.get("status", "PENDIENTE"),
                requiere_confirmacion=True if action_data.get("status") == "PENDIENTE" else False
            )

            # Si la IA determina que ya debe ejecutarse (por confirmación en chat)
            if accion_obj.estado == "EJECUTADA":
                self._ejecutar_logica_accion(accion_obj, request.user)

        return response.Response({
            "mensaje_ia": ai_data.get("message"),
            "accion": AccionIASerializer(accion_obj).data if accion_obj else None,
            "suggested_actions": ai_data.get("suggested_actions", []),
            "options": ai_data.get("options", []),
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

        # Guardar temporalmente para procesar
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_audio:
            for chunk in audio_file.chunks():
                temp_audio.write(chunk)
            temp_path = temp_audio.name

        try:
            ai_service = AIService()
            texto = ai_service.transcribe_audio(temp_path)
            return response.Response({"texto": texto})
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _ejecutar_logica_accion(self, accion, user):
        """
        Lógica centralizada para ejecutar acciones de negocio.
        """
        logger.info(f"Ejecutando lógica de acción IA: {accion.accion} para usuario {user.id}")
        
        if accion.accion == "CAMBIAR_USUARIO":
            nuevo_nombre = accion.parametros.get("nuevo_nombre")
            nuevo_apellido = accion.parametros.get("nuevo_apellido")
            if nuevo_nombre or nuevo_apellido:
                from modulos.administracion_acceso_configuracion.models import Usuario
                update_data = {}
                if nuevo_nombre: update_data['nombres'] = nuevo_nombre
                if nuevo_apellido: update_data['apellidos'] = nuevo_apellido
                
                Usuario.objects.filter(id=user.id).update(**update_data)
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": "Datos de usuario actualizados correctamente."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "No se proporcionaron datos para actualizar"}
        
        elif accion.accion == "CAMBIAR_TELEFONO":
            nuevo_tel = accion.parametros.get("nuevo_telefono") or accion.parametros.get("phone")
            if nuevo_tel:
                from modulos.administracion_acceso_configuracion.models import Usuario
                Usuario.objects.filter(id=user.id).update(telefono=nuevo_tel)
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": f"Teléfono actualizado a {nuevo_tel} correctamente."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Falta el parámetro del nuevo teléfono"}

        elif accion.accion == "CAMBIAR_CONTRASENA":
            nueva_pass = accion.parametros.get("nueva_contrasena")
            if nueva_pass:
                # Nota: En un sistema real usaríamos set_password, aquí actualizamos para consistencia
                user.set_password(nueva_pass)
                user.save()
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": "Contraseña actualizada correctamente."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Falta la nueva contraseña"}

        elif accion.accion == "ACTUALIZAR_PREFERENCIAS":
            noti_email = accion.parametros.get("noti_email")
            noti_push = accion.parametros.get("noti_push")
            
            update_fields = {}
            if noti_email is not None:
                if isinstance(noti_email, str):
                    noti_email = noti_email.lower() in ['true', '1', 't', 'y', 'yes']
                update_fields['noti_email'] = bool(noti_email)
            if noti_push is not None:
                if isinstance(noti_push, str):
                    noti_push = noti_push.lower() in ['true', '1', 't', 'y', 'yes']
                update_fields['noti_push'] = bool(noti_push)
                
            if update_fields:
                from modulos.administracion_acceso_configuracion.models import Usuario
                Usuario.objects.filter(id=user.id).update(**update_fields)
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": "Preferencias de notificación actualizadas correctamente."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "No se proporcionaron preferencias para actualizar."}

        elif accion.accion == "CAMBIAR_NOMBRE_EMPRESA":
            nuevo_nombre = accion.parametros.get("nuevo_nombre")
            if nuevo_nombre:
                from modulos.administracion_acceso_configuracion.models import Empresa
                Empresa.objects.filter(id=accion.empresa.id).update(nombre=nuevo_nombre)
                accion.estado = "EJECUTADA"
                accion.resultado = {"status": "success", "message": f"Nombre de empresa actualizado a {nuevo_nombre}."}
            else:
                accion.estado = "FALLIDA"
                accion.resultado = {"status": "error", "message": "Falta el nuevo nombre de la empresa"}

        elif accion.accion in ["COMPRAR_PLAN", "RELLENAR_PAGO", "CANCELAR_CAMBIO"]:
            # Estas acciones son principalmente para el frontend (llenado visual)
            # El backend solo las marca como ejecutadas cuando el usuario confirma en el chat
            # que "desea que la IA lo rellene" o "está listo".
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

        elif accion.accion in ["BUSCAR_PLAN", "VER_PLAN", "EDITAR_PLAN", "CAMBIAR_ESTADO_PLAN", "AGREGAR_DETALLE_PLAN"]:
            accion.estado = "EJECUTADA"
            accion.resultado = {"status": "success", "message": f"Acción de plan {accion.accion} delegada al frontend."}
            
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
