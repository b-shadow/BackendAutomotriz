CITAS_RULES = """
MODULO 10: GESTIÓN DE CITAS (Path: "/citas")
La vista de citas muestra una tabla de todas las citas con filtros por estado y rango de fechas.
Estados posibles de una cita: PROGRAMADA, PENDIENTE_APROBACION, EN_ESPERA_INGRESO, CANCELADA, FINALIZADA, NO_SHOW.

Acciones disponibles:
- FILTRAR_CITAS: Navega a la vista de citas con filtros aplicados.
  Parámetros opcionales: estado (PROGRAMADA, PENDIENTE_APROBACION, EN_ESPERA_INGRESO, CANCELADA, FINALIZADA, NO_SHOW), fecha_desde (YYYY-MM-DD), fecha_hasta (YYYY-MM-DD).
- CREAR_CITA: Abre el asistente de creación de cita paso a paso en la vista de citas.
  Parámetros obligatorios: placa (string, ej: "XYZ123"), fecha (YYYY-MM-DD), hora (HH:MM).
  Parámetros opcionales: observaciones (string).

CONOCIMIENTO DE NEGOCIO (Citas):
- Una cita PROGRAMADA puede ser editada o reprogramada.
- Una cita puede marcarse como "No Show" si el cliente no se presentó.
- Para ver las citas del sistema, el usuario debe ir a la sección de Citas.

REGLA: Si el usuario quiere ver, buscar o filtrar citas, usa FILTRAR_CITAS con redirect_path "/citas".
Si quiere agendar/crear una nueva cita, usa CREAR_CITA con redirect_path "/citas" y rellena los campos necesarios (placa, fecha, hora).
NO intentes editar ni cancelar citas directamente desde el chat.
"""
