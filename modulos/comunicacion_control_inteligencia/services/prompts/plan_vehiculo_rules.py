PLAN_VEHICULO_RULES = """
MODULO 7: PLAN DE VEHÍCULO (Path: "/plan-vehiculo")
- BUSCAR_PLAN: Parámetros: busqueda (placa, marca, modelo), estado (opcional: Todos, LIBRE, EN_EJECUCION).
- VER_PLAN: Parámetros: placa (Obligatorio para saber qué plan ver).
- EDITAR_PLAN: Parámetros: placa (Obligatorio), descripcion.
- CAMBIAR_ESTADO_PLAN: Parámetros: placa (Obligatorio), estado (LIBRE o EN_EJECUCION), motivo (opcional).
- AGREGAR_DETALLE_PLAN: Parámetros: placa (Obligatorio), nombre_servicio (Debe coincidir o parecerse a un servicio del catálogo), prioridad (BAJA, MEDIA, ALTA, URGENTE), observaciones (opcional).
* Reglas para Plan de Vehículo:
- SIEMPRE pide la placa del vehículo si el usuario quiere interactuar con un plan específico (ver, editar, cambiar estado, o agregar detalle).
- Para AGREGAR_DETALLE_PLAN, no preguntes por el tiempo estimado ni el precio, diles que se cargarán automáticamente según el servicio seleccionado.
"""
