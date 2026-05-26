REPORTES_RULES = """
MODULO 9: REPORTES Y ESTADISTICAS (Path: "/reportes")
- VER_REPORTE_GLOBAL: Parametros opcionales: desde (YYYY-MM-DD), hasta (YYYY-MM-DD), estado_cita, canal_origen.
- VER_REPORTE_VEHICULO: Parametros opcionales: desde (YYYY-MM-DD), hasta (YYYY-MM-DD), placa, marca, modelo, estado_cita, canal_origen.
- VER_REPORTE_PRESUPUESTO: Parametros opcionales: desde (YYYY-MM-DD), hasta (YYYY-MM-DD), placa, estado_presupuesto.
- VER_REPORTE_INVENTARIO: Parametros opcionales: desde (YYYY-MM-DD), hasta (YYYY-MM-DD), codigo_servicio, nombre_servicio.
- EXPORTAR_REPORTE: Parametros obligatorios: formato (CSV, EXCEL, HTML).

Reglas de interpretacion para reportes por texto/voz:
- "vehiculo con mas citas" -> VER_REPORTE_GLOBAL.
- "vehiculo con mas detalles resueltos" -> VER_REPORTE_GLOBAL.
- "vehiculos en taller vs total" -> VER_REPORTE_GLOBAL.
- "historial de citas de placa X" -> VER_REPORTE_VEHICULO con placa.
- "detalles de cita de placa X" -> VER_REPORTE_VEHICULO con placa.
- "tiempo en taller de placa X" -> VER_REPORTE_VEHICULO con placa.
- "filtra por marca/modelo/estado/canal" -> VER_REPORTE_VEHICULO con esos parametros.
- Si piden exportar y no especifican formato, usar EXCEL.
"""
