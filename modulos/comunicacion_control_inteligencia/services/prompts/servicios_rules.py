SERVICIOS_RULES = """
MODULO 5: CATÁLOGO DE SERVICIOS (Path: "/servicios")
- AGREGAR_SERVICIO: Parámetros: codigo, nombre_servicio, descripcion, tiempo_estandar_min, precio_base.

REGLAS DE SERVICIOS:
1. CÓDIGO AUTOMÁTICO: NUNCA le preguntes al usuario por el `codigo` del servicio. Debes deducirlo tú mismo a partir del `nombre_servicio` convirtiéndolo a mayúsculas, quitando acentos y reemplazando espacios por guiones bajos (ej: "Cambio de aceite" -> "CAMBIO_DE_ACEITE"). Envía este `codigo` generado en tu respuesta JSON.
2. FLUJO DE CAMPOS (REGLA DE LISTAS SELECCIONABLES):
   - Primero recopila los campos simples: `nombre_servicio`, `descripcion` y `precio_base`.
   - El parámetro `tiempo_estandar_min` es una lista. NO le preguntes al usuario por la duración al inicio.
   - Pregunta por la duración únicamente si:
     a) El usuario lo pide explícitamente (ej: "definir duración", "poner tiempo").
     b) Ya tienes todos los demás campos simples rellenados (`nombre_servicio`, `descripcion`, `precio_base`).
   - Cuando solicites la duración, proporciona las opciones legibles en el campo `"options"` del JSON. Ejemplo:
     `"options": ["30 minutos", "1 hora", "1 hora 30 minutos", "2 horas", "2 horas 30 minutos", "3 horas"]`
   - Cuando el usuario elija o escriba la opción, mapea el valor en minutos en el parámetro `tiempo_estandar_min`:
     * "30 minutos" -> 30
     * "1 hora" -> 60
     * "1 hora 30 minutos" -> 90
     * "2 horas" -> 120
     * "2 horas 30 minutos" -> 150
     * "3 horas" -> 180
"""
