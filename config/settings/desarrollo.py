"""
Configuración específica para DESARROLLO.
Extiende la configuración base.
"""
from .base import *

DEBUG = True
ENVIRONMENT = "desarrollo"

# Seguridad relajada para desarrollo
ALLOWED_HOSTS = ["*"]

# ✅ CORS PARA DESARROLLO: PERMITIR TODOS LOS ORÍGENES
# En desarrollo, es más fácil permitir cualquier origen que parsear puertos dinámicos
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# Agregar explícitamente a CORS_ALLOWED_ORIGINS para ser exhaustivo
CORS_ALLOWED_ORIGINS = [
    "https://frontend-automotriz.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://127.0.0.1:8000",
]

# ✅ CSRF: permitir estos orígenes para POST requests
CSRF_TRUSTED_ORIGINS = [
    "https://frontend-automotriz.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]

# Email: consola para debug
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Desactivar HTTPS en desarrollo local
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Swagger/API Docs accesible
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
}

# REST Framework: Usar configuración base (JWTAuthentication estándar)
# OptionalJWTAuthentication ya no es necesario con AUTH_USER_MODEL correcto

# Logs más verbosos
LOG_LEVEL = "DEBUG"