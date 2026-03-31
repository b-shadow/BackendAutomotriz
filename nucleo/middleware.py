"""
Middleware personalizado.
Por ahora vacío, se puede usar para tenant detection, auditoría, etc.
"""
import logging

logger = logging.getLogger(__name__)


class AuditMiddleware:
    """
    Middleware para registrar requests importantes en la auditoría.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Pre-processing
        response = self.get_response(request)
        # Post-processing
        return response
