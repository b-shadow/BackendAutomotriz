"""
Utilidades comunes para toda la app.
"""
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def obtener_fecha_hace_n_dias(n_dias: int) -> datetime:
    """
    Retorna la fecha de hace N días.
    """
    return datetime.now() - timedelta(days=n_dias)


def obtener_fecha_hace_n_horas(n_horas: int) -> datetime:
    """
    Retorna la fecha de hace N horas.
    """
    return datetime.now() - timedelta(hours=n_horas)


def generar_token_temporal(largo: int = 32) -> str:
    """
    Genera un token aleatorio para password reset, email verification, etc.
    """
    import secrets

    return secrets.token_urlsafe(largo)


def es_email_valido(email: str) -> bool:
    """
    Validación simple de email. Para producción, usar django-email-validator.
    """
    import re

    patron = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return re.match(patron, email) is not None


def obtener_cliente_ip(request) -> str:
    """
    Obtiene la IP real del cliente considerando proxies.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        ip = x_forwarded_for.split(",")[0]
    else:
        ip = request.META.get("REMOTE_ADDR")
    return ip
