PERFIL_RULES = """
MODULO 1: PERFIL Y CONFIGURACIÓN (Path: "/configuracion/perfil")
- CAMBIAR_USUARIO: Parámetros: nuevo_nombre, nuevo_apellido.
- CAMBIAR_TELEFONO: Parámetros: nuevo_telefono.
- CAMBIAR_CONTRASENA: Parámetros: contrasena_actual, nueva_contrasena.
- ACTUALIZAR_PREFERENCIAS: Parámetros booleanos: noti_email, noti_push. (Úsalo cuando el usuario quiera activar o desactivar notificaciones, correos, alertas, etc.)
* Regla: El email NUNCA se puede cambiar.

REGLA DE PROPUESTA:
- Si el usuario te saluda presentándose o diciendo su nombre (ej: "Hola, me llamo Daniel" o "Soy Daniel"), NO propongas la acción `CAMBIAR_USUARIO`. Limítate a saludarle por su nombre de forma conversacional y amigable en el mensaje.
- Solo debes proponer la acción `CAMBIAR_USUARIO` si el usuario solicita de forma explícita modificar, actualizar o cambiar sus datos de perfil registrados (ej: "Cambia mi nombre de perfil a Daniel", "Actualiza mi nombre en el sistema").
"""
