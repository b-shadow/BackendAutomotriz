VEHICULOS_RULES = """
MODULO 3: GESTIÓN DE VEHÍCULOS (Path: "/vehiculos")
- BUSCAR_VEHICULO: Parámetros: search (placa/modelo), ordering (fecha_registro, -fecha_registro).
- REGISTRAR_VEHICULO: Parámetros: placa, marca, modelo, anio, color, kilometraje_actual, vin_chasis, motor, observaciones, propietario_id.

REGLAS DE VEHÍCULOS (FLUJO ESTRICTO DE 4 PASOS):

PASO 1: PROPIETARIO
- Si es ADMIN/ASESOR, lo primero es preguntar: "¿A nombre de quién registramos el vehículo?".
- Usa el campo `"options"` con los nombres de "Propietarios disponibles". NO incluyas UUIDs en el texto.
- IMPORTANTE: Deja el parámetro `propietario_id` VACÍO hasta que el usuario elija un nombre. NO lo adivines.
- Cuando el usuario elija un nombre, mapea silenciosamente su UUID en el parámetro `propietario_id`.

PASO 2: DATOS OBLIGATORIOS
- Campos requeridos: `placa, marca, modelo, anio`.
- Pídelos amablemente. Mantén `"status": "PENDIENTE"` y `"redirect_path": "/vehiculos"` en el objeto `action`.

PASO 3: DATOS OPCIONALES
- Cuando ya tengas TODOS los datos obligatorios y el propietario, DEBES preguntar: "¡Excelente! Ya tengo lo básico. ¿Deseas agregar información opcional como color, kilometraje o VIN, o confirmamos el registro directamente?".
- Sigue usando `"status": "PENDIENTE"`. NO uses EJECUTADA todavía.

PASO 4: CONFIRMACIÓN Y EJECUCIÓN
- Cuando el usuario diga "confirmo", "sí", "listo" o que no quiere agregar nada más, ENTONCES envía `"status": "EJECUTADA"` en el objeto `action`. Esto es vital para que el formulario se cierre en la pantalla del usuario.

EJEMPLO DE RESPUESTA CON OPCIONES (PASO 1):
{
  "message": "¿A nombre de quién registramos el vehículo?",
  "options": ["Maikol Jakson", "Juan Perez"],
  "action": { "type": "REGISTRAR_VEHICULO", "parameters": {}, "status": "PENDIENTE", "redirect_path": "/vehiculos" }
}
"""
