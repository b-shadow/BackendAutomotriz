"""
Configuración específica para PRODUCCIÓN.
Extiende la configuración base con ajustes de seguridad.
"""
from .base import *

DEBUG = False
ENVIRONMENT = "produccion"

# Seguridad: HTTPS obligatorio
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000  # 1 año
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"

# Solo CORS de producción
CORS_ALLOWED_ORIGINS = env(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "https://frontend-automotriz.vercel.app",
        "https://backendautomotriz.onrender.com",
    ],
)

# Headers de seguridad - con Stripe allowlisted
SECURE_CONTENT_SECURITY_POLICY = {
    # Scripts: self + Stripe.js
    "script-src": (
        "'self'",
        "https://js.stripe.com",
        "https://m.stripe.com",
    ),
    # Conectar a APIs (fetch/xhr)
    "connect-src": (
        "'self'",
        "https://api.stripe.com",
        "https://q.stripe.com",
        "https://r.stripe.com",
        "https://m.stripe.com",
    ),
    # Frames (para 3D Secure y métodos alternativos)
    "frame-src": (
        "https://js.stripe.com",
        "https://m.stripe.com",
    ),
    # Imágenes (logos, etc)
    "img-src": (
        "'self'",
        "https://a.stripe.com",
        "https:",
    ),
    # Default fallback
    "default-src": ("'self'",),
}

# Allowed hosts desde .env
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=["tudominio.com"])

# Email: Mailtrap o similar en producción
# (se configura via .env)

# Logs normales
LOG_LEVEL = "INFO"

# API Docs restringida a autenticados
SPECTACULAR_SETTINGS = {
    **SPECTACULAR_SETTINGS,
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
}

# Desactivar debug toolbar
TOOLBAR_INSTALLED = False
