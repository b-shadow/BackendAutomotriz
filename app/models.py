"""Capa de compatibilidad temporal de modelos.

Este modulo mantiene los nombres historicos (`app.models`) mientras la
migracion modular avanza. Los modelos reales viven en `modulos/*/models.py`.
"""

# 3.5.1 Administracion, Acceso y Configuracion
from modulos.administracion_acceso_configuracion.models import *  # noqa: F403,F401

# 3.5.2 Vehiculos, Servicios, Plan y Citas
from modulos.vehiculos_servicios_plan_citas.models import *  # noqa: F403,F401

# 3.5.3 Atencion Tecnica y Ejecucion del Servicio
from modulos.atencion_tecnica_ejecucion.models import *  # noqa: F403,F401

# 3.5.4 Inventario, Proveedores y Gestion Administrativa
from modulos.inventario_proveedores_administracion.models import *  # noqa: F403,F401

# 3.5.5 Comunicacion, Control e Inteligencia
from modulos.comunicacion_control_inteligencia.models import *  # noqa: F403,F401

