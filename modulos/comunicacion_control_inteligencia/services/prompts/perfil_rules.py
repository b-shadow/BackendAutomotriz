PERFIL_RULES = """
MODULO 1: PERFIL Y CONFIGURACIÓN (Path: "/configuracion/perfil")
- CAMBIAR_USUARIO: Parámetros: nuevo_nombre, nuevo_apellido.
- CAMBIAR_TELEFONO: Parámetros: nuevo_telefono.
- CAMBIAR_CONTRASENA: Parámetros: contrasena_actual, nueva_contrasena.
- ACTUALIZAR_PREFERENCIAS: Parámetros booleanos: noti_email, noti_push. (Úsalo cuando el usuario quiera activar o desactivar notificaciones, correos, alertas, etc.)
* Regla: El email NUNCA se puede cambiar.
"""
