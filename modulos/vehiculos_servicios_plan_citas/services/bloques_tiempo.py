"""Utilidades para manejo de bloques fijos de tiempo."""

from datetime import time

BLOQUE_MINUTOS = 30
MINUTOS_DIA = 24 * 60


def time_a_minutos(hora: time) -> int:
    """Convierte un `time` a minutos desde medianoche."""
    return hora.hour * 60 + hora.minute


def es_bloque_valido(minuto: int) -> bool:
    """Valida que el minuto pertenezca a un bloque exacto de 30 minutos."""
    return 0 <= minuto < MINUTOS_DIA and minuto % BLOQUE_MINUTOS == 0

