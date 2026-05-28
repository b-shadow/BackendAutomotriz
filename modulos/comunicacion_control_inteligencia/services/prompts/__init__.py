from .base_rules import BASE_RULES
from .perfil_rules import PERFIL_RULES
from .suscripcion_rules import SUSCRIPCION_RULES
from .vehiculos_rules import VEHICULOS_RULES
from .empresa_rules import EMPRESA_RULES
from .servicios_rules import SERVICIOS_RULES
from .espacios_rules import ESPACIOS_RULES
from .plan_vehiculo_rules import PLAN_VEHICULO_RULES
from .bitacora_rules import BITACORA_RULES
from .reportes_rules import REPORTES_RULES
from .citas_rules import CITAS_RULES
from .navegacion_rules import NAVEGACION_RULES

from .base_rules import BASE_RULES
from .perfil_rules import PERFIL_RULES
from .suscripcion_rules import SUSCRIPCION_RULES
from .vehiculos_rules import VEHICULOS_RULES
from .empresa_rules import EMPRESA_RULES
from .servicios_rules import SERVICIOS_RULES
from .espacios_rules import ESPACIOS_RULES
from .plan_vehiculo_rules import PLAN_VEHICULO_RULES
from .bitacora_rules import BITACORA_RULES
from .reportes_rules import REPORTES_RULES
from .citas_rules import CITAS_RULES
from .navegacion_rules import NAVEGACION_RULES

def get_full_prompt(context_str, query_text=""):
    active_rules = []
    
    import unicodedata
    def clean_text(t):
        t = t.lower()
        return "".join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    
    q = clean_text(query_text)
    
    # 1. Perfil
    if any(kw in q for kw in ["perfil", "nombre", "apellido", "telefono", "contrasena", "clave", "cuenta", "notificacion", "correo", "email", "push"]):
        active_rules.append(PERFIL_RULES)
        
    # 2. Suscripcion
    if any(kw in q for kw in ["suscripcion", "plan", "pago", "pagar", "factura", "precio", "comprar"]):
        active_rules.append(SUSCRIPCION_RULES)
        
    # 3. Vehículos
    if any(kw in q for kw in ["vehiculo", "carro", "auto", "placa", "marca", "modelo", "anio", "color", "kilometraje", "chasis", "motor", "buscar"]):
        active_rules.append(VEHICULOS_RULES)
        
    # 4. Empresa
    if any(kw in q for kw in ["empresa", "taller", "nombre empresa", "configurar empresa"]):
        active_rules.append(EMPRESA_RULES)
        
    # 5. Servicios
    if any(kw in q for kw in ["servicio", "catalogo", "duracion", "aceite", "mantenimiento", "tiempo", "costo", "precio"]):
        active_rules.append(SERVICIOS_RULES)
        
    # 6. Espacios
    if any(kw in q for kw in ["espacio", "bahia", "horario", "trabajo", "disponibilidad"]):
        active_rules.append(ESPACIOS_RULES)
        
    # 7. Plan Vehiculo
    if any(kw in q for kw in ["plan", "preventivo", "mantenimiento"]):
        active_rules.append(PLAN_VEHICULO_RULES)
        
    # 8. Bitacora
    if any(kw in q for kw in ["bitacora", "registro", "auditoria", "evento", "exportar"]):
        active_rules.append(BITACORA_RULES)
        
    # 9. Reportes
    if any(kw in q for kw in ["reporte", "estadistica", "grafico", "dinamico"]):
        active_rules.append(REPORTES_RULES)
        
    # 10. Citas
    if any(kw in q for kw in ["cita", "agendar", "agenda", "reservar", "reserva"]):
        active_rules.append(CITAS_RULES)

    rules_str = "\n\n".join(active_rules)

    return f"""
{context_str}

{BASE_RULES}

{rules_str}

{NAVEGACION_RULES}

---
EJEMPLOS DE RESPUESTA CORRECTA:

Usuario: "Hola"
IA: {{"message": "¡Hola! Soy AutoTaller AI. ¿En qué puedo ayudarte hoy?", "options": ["Ver mis vehículos", "Agendar una cita", "Ver reportes"], "suggested_actions": [], "action": null}}

Usuario: "Hola, soy Daniel"
IA: {{"message": "¡Hola, Daniel! Un gusto. ¿En qué puedo ayudarte?", "options": [], "suggested_actions": [], "action": null}}

Usuario: "Registra mi vehículo 2024 placa XYZ123 marca Ford modelo Fiesta"
IA: {{"message": "¡Excelente! Preparando el registro de tu Ford Fiesta. ¿Deseas agregar color o kilometraje?", "options": [], "suggested_actions": [], "action": {{"type": "REGISTRAR_VEHICULO", "parameters": {{"placa": "XYZ123", "marca": "Ford", "modelo": "Fiesta", "anio": 2024}}, "status": "PENDIENTE", "redirect_path": "/vehiculos"}}}}
"""

