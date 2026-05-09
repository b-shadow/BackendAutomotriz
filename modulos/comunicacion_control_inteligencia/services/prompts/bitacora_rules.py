BITACORA_RULES = """
MODULO 8: BITÁCORA DE AUDITORÍA (Path: "/bitacora")
- FILTRAR_BITACORA: Parámetros opcionales: search (texto libre), accion (nombre de la acción a buscar), fecha_desde (formato YYYY-MM-DD), fecha_hasta (formato YYYY-MM-DD), orden (-created_at o created_at).
- EXPORTAR_BITACORA: Parámetros obligatorios: formato (CSV, Excel o HTML).
* Regla para Bitácora: 
  - Si el usuario menciona 'más recientes', 'nuevos' -> orden = "-created_at". Si menciona 'antiguos' -> orden = "created_at".
  - Al pedir exportar, siempre debes deducir o pedir el formato (por defecto asume Excel si no especifica, pero envía el formato elegido: csv, excel, html).
"""
