"""
Punto de entrada modular para servicios de administracion/acceso/configuracion.
"""

from modulos.administracion_acceso_configuracion.services.empresa_setup import setup_empresa_nueva
from modulos.administracion_acceso_configuracion.services.auditoria_service import *  # noqa: F401,F403

__all__ = ["setup_empresa_nueva"]
