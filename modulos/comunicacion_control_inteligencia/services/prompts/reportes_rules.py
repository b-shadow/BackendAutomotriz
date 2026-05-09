REPORTES_RULES = """
MODULO 9: REPORTES Y ESTADÍSTICAS (Path: "/reportes")
- VER_REPORTE_GLOBAL: Parámetros opcionales: desde (formato YYYY-MM-DD), hasta (formato YYYY-MM-DD).
- VER_REPORTE_VEHICULO: Parámetros opcionales: desde (formato YYYY-MM-DD), hasta (formato YYYY-MM-DD), placa (placa del vehículo a buscar).
- VER_REPORTE_PRESUPUESTO: Parámetros opcionales: desde (formato YYYY-MM-DD), hasta (formato YYYY-MM-DD).
- VER_REPORTE_INVENTARIO: Parámetros opcionales: desde (formato YYYY-MM-DD), hasta (formato YYYY-MM-DD).
- EXPORTAR_REPORTE: Parámetros obligatorios: formato (CSV, EXCEL, HTML).

* Reglas para Reportes:
- Si el usuario pide un reporte global de ventas o estadísticas de ingresos, usa VER_REPORTE_GLOBAL.
- Si el usuario pide saber cuánto se le cobró a una placa en específico, usa VER_REPORTE_VEHICULO.
- Si pide ver reportes sobre cotizaciones o presupuestos, usa VER_REPORTE_PRESUPUESTO.
- Si pide ver reportes de inventario, catálogo, o servicios más vendidos, usa VER_REPORTE_INVENTARIO.
- Si pide exportar el reporte, asume formato Excel si no lo especifica, y usa EXPORTAR_REPORTE.
"""
