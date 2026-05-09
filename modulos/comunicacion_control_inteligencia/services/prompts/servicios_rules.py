SERVICIOS_RULES = """
MODULO 5: CATÁLOGO DE SERVICIOS (Path: "/servicios")
- AGREGAR_SERVICIO: Parámetros: codigo, nombre_servicio, descripcion, tiempo_estandar_min, precio_base.
* Regla estricta para AGREGAR_SERVICIO: NUNCA le preguntes al usuario por el `codigo` del servicio. Debes deducirlo tú mismo a partir del `nombre_servicio` convirtiéndolo a mayúsculas y reemplazando espacios por guiones bajos (ej: "Cambio de aceite" -> "CAMBIO_DE_ACEITE"). Asegúrate de enviar este `codigo` generado en tu respuesta JSON.
"""
