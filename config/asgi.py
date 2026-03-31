"""
ASGI config para SaaS Backend.
Exponemos la aplicación ASGI para servidores como Daphne o Uvicorn.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.desarrollo")

application = get_asgi_application()
