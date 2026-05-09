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

def get_full_prompt(context_str):
    return f"""
{context_str}

{BASE_RULES}

{PERFIL_RULES}

{SUSCRIPCION_RULES}

{VEHICULOS_RULES}

{EMPRESA_RULES}

{SERVICIOS_RULES}

{ESPACIOS_RULES}

{PLAN_VEHICULO_RULES}

{BITACORA_RULES}

{REPORTES_RULES}

---
EJEMPLOS DE RESPUESTA:
Usuario: "Busca mi Toyota"
IA: {{ "message": "Buscando tus vehículos Toyota...", "action": {{ "type": "BUSCAR_VEHICULO", "parameters": {{ "search": "Toyota" }}, "status": "PENDIENTE", "redirect_path": "/vehiculos" }} }}

Usuario: "Registra mi vehículo 2024 placa XYZ123 marca Ford modelo Fiesta"
IA: {{ "message": "¡Excelente! Preparando el registro de tu Ford Fiesta. ¿Deseas agregar el color o kilometraje?", "action": {{ "type": "REGISTRAR_VEHICULO", "parameters": {{ "placa": "XYZ123", "marca": "Ford", "modelo": "Fiesta", "anio": 2024 }}, "status": "PENDIENTE", "redirect_path": "/vehiculos" }} }}
"""
