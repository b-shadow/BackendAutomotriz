ESPACIOS_RULES = """
MODULO 6.1: ESPACIOS DE TRABAJO (Path: "/gestion/espacios-de-trabajo")
- REGISTRAR_ESPACIO: Parámetros: codigo, nombre, tipo, observaciones.
- EDITAR_ESPACIO: Parámetros: espacio_identificador (código o nombre para buscarlo), codigo, nombre, tipo, observaciones, activo (true/false).

REGLAS DE ESPACIOS DE TRABAJO (FLUJO DE RECOPILACIÓN):
1. PRIMERO DATOS SIMPLES:
   - Empieza solicitando los campos simples: `codigo` y `nombre`.
2. TIPO (LISTA DE OPCIONES):
   - El parámetro `tipo` debe ser seleccionado obligatoriamente de esta lista: TALLER, CHEQUEO, GARAJE, LAVADO.
   - NO preguntes por el `tipo` al inicio. Pregunta por el `tipo` únicamente si:
     a) El usuario lo pide explícitamente (ej: "definir tipo").
     b) Ya tienes los campos simples (`codigo` y `nombre`) rellenados.
   - Cuando preguntes por el `tipo`, debes proveer las opciones correspondientes en el campo `"options"` del JSON: `["TALLER", "CHEQUEO", "GARAJE", "LAVADO"]`.

MODULO 6.2: HORARIOS (Path: "/gestion/horarios")
- VER_HORARIOS_ESPACIO: Parámetros: espacio_identificador (código o nombre del espacio).
- AGREGAR_HORARIO_ESPACIO: Parámetros: espacio_identificador, dia (Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo), hora_inicio (HH:MM), hora_fin (HH:MM).
- EDITAR_HORARIO_ESPACIO: Parámetros: espacio_identificador, dia (Lunes, Martes, Miércoles, Jueves, Viernes, Sábado, Domingo), hora_inicio (HH:MM), hora_fin (HH:MM).
* Reglas para Espacios y Horarios:
  - Para agregar o editar horarios, debes solicitar el día de la semana, hora de inicio y hora final (en formato de 24 horas, ej. 08:00, 18:00).
  - Siempre debes obtener primero a qué espacio (taller o espacio) se le aplicarán los cambios (espacio_identificador).
"""
