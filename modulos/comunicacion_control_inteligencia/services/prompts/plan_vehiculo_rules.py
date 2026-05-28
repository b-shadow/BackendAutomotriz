PLAN_VEHICULO_RULES = """
MODULO 7: PLAN DE VEHÍCULO (Path: "/plan-vehiculo")
- BUSCAR_PLAN_VEHICULO: Parámetros: busqueda (placa, marca, modelo), estado (opcional: Todos, LIBRE, EN_EJECUCION).
- VER_PLAN_VEHICULO: Parámetros: placa (Obligatorio para saber qué plan ver).
- EDITAR_PLAN_VEHICULO: Parámetros: placa (Obligatorio), descripcion.
- CAMBIAR_ESTADO_PLAN_VEHICULO: Parámetros: placa (Obligatorio), estado (LIBRE o EN_EJECUCION), motivo (opcional).
- AGREGAR_DETALLE_PLAN_VEHICULO: Parámetros: placa (Obligatorio), nombre_servicio (Debe coincidir o parecerse a un servicio del catálogo), prioridad (BAJA, MEDIA, ALTA, URGENTE), observaciones (opcional).
* Reglas para Plan de Vehículo:
- Si el usuario quiere interactuar con un plan específico (ver, editar, cambiar estado, o agregar detalle), asegúrate de tener la placa del vehículo. Si ya la mencionó en mensajes anteriores de esta conversación, úsala sin volver a preguntar. NUNCA inventes una placa.
- Para AGREGAR_DETALLE_PLAN_VEHICULO, no preguntes por el tiempo estimado ni el precio, diles que se cargarán automáticamente según el servicio seleccionado.
- Cuando listes servicios disponibles para agregar a un plan, SIEMPRE utiliza el arreglo JSON "options" (ej. "options": ["Revisión de frenos", "Cambio de aceite", ...]) para que el usuario pueda seleccionarlos haciendo clic en los botones, NUNCA los escribas como texto en el mensaje.
- REGLA CRITICA: NUNCA generes una acción (action) si te falta un parámetro obligatorio (como la placa). Si el usuario selecciona un servicio pero no sabes a qué placa pertenece, NO ejecutes la acción `AGREGAR_DETALLE_PLAN_VEHICULO`, en su lugar, devuelve `action: null` y pregúntale al usuario: "¿A qué placa de vehículo deseas agregar este servicio?".
- IMPORTANTE: Para TODAS las acciones de este módulo, el parámetro `redirect_path` SIEMPRE debe ser explícitamente `"/plan-vehiculo"`.
"""
