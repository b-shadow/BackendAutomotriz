SUSCRIPCION_RULES = """
MODULO 2: SUSCRIPCIONES Y PAGOS (Path: "/gestion/suscripcion")
- COMPRAR_PLAN: Parámetros: plan_nombre (Starter, Pro, Enterprise).
- RELLENAR_PAGO: Parámetros: nombre_titular, numero_tarjeta, fecha_expiracion, cvc.
- CANCELAR_CAMBIO: No requiere parámetros.

CONOCIMIENTO DE NEGOCIO (Planes):
- Starter ($29 USD/mes): Talleres pequeños.
- Pro ($79 USD/mes): Talleres en crecimiento.
- Enterprise ($199 USD/mes): Control total.
"""
