"""
Configuración base de Django para SaaS Backend.
Carga variables de entorno y define configuraciones comunes.
"""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
import environ
from decouple import config as decouple_config

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(
    DEBUG=(bool, False),
    ENVIRONMENT=(str, "desarrollo"),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
)

# Lee archivo .env si existe
if os.path.isfile(os.path.join(BASE_DIR, ".env")):
    environ.Env.read_env(os.path.join(BASE_DIR, ".env"))

# === CORE SETTINGS ===
SECRET_KEY = env("SECRET_KEY", default="django-insecure-changeme")
DEBUG = env("DEBUG", default=False)
ENVIRONMENT = env("ENVIRONMENT", default="desarrollo")
ALLOWED_HOSTS = env("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# === DJANGO APPS ===
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
]

LOCAL_APPS = [
    # Legacy temporal: contiene AUTH_USER_MODEL y migraciones historicas.
    # Se retirara cuando los modelos esten 100% movidos a modulos/.
    "app",
    "modulos.administracion_acceso_configuracion",
    "modulos.vehiculos_servicios_plan_citas",
    "modulos.atencion_tecnica_ejecucion",
    "modulos.inventario_proveedores_administracion",
    "modulos.comunicacion_control_inteligencia",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# === MIDDLEWARE ===
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "app.middleware.TenantMiddleware",
]

ROOT_URLCONF = "config.urls"

# === TEMPLATES ===
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# === DATABASE (Neon PostgreSQL) ===
# Primero intenta leer DATABASE_URL; si no existe, usa configuración de desarrollo
if "DATABASE_URL" in os.environ:
    DATABASES = {
        "default": dj_database_url.config(
            default=os.environ.get("DATABASE_URL"),
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", default="saas_db"),
            "USER": env("DB_USER", default="postgres"),
            "PASSWORD": env("DB_PASSWORD", default="postgres"),
            "HOST": env("DB_HOST", default="localhost"),
            "PORT": env("DB_PORT", default=5432),
            "CONN_MAX_AGE": 600,
            "CONN_HEALTH_CHECKS": True,
            "OPTIONS": {
                "sslmode": "require" if ENVIRONMENT == "produccion" else "prefer",
            },
        }
    }

# === PASSWORD VALIDATION ===
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# === AUTHENTICATION ===
AUTH_USER_MODEL = "administracion_acceso_configuracion.Usuario"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

# === INTERNATIONALIZATION ===
LANGUAGE_CODE = "es-es"
TIME_ZONE = "America/La_Paz"
USE_I18N = True
USE_TZ = True

# === STATIC & MEDIA FILES ===
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_DIRS = [d for d in [os.path.join(BASE_DIR, "static")] if os.path.isdir(d)]

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# === DEFAULT PRIMARY KEY TYPE ===
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# === CORS CONFIGURATION ===
# === CORS CONFIGURATION ===
CORS_ALLOWED_ORIGINS = [
    "https://frontend-automotriz.vercel.app",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
]
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

# Si luego usas cookies/CSRF (formularios o admin desde front)
CSRF_TRUSTED_ORIGINS = [
    "https://frontend-automotriz.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# === DJANGO REST FRAMEWORK ===
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
    ],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "nucleo.autenticacion.OptionalJWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "nucleo.paginacion.PaginacionEstandar",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "TEST_REQUEST_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

# === SIMPLE JWT ===
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=int(env("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", default=15))
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        days=int(env("JWT_REFRESH_TOKEN_EXPIRE_DAYS", default=7))
    ),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SECRET_KEY", default=SECRET_KEY),
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JTI_CLAIM": "jti",
    "TOKEN_TYPE_CLAIM": "token_type",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# === EMAIL CONFIGURATION ===
EMAIL_BACKEND = env(
    "EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=1025)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@saas.com")
SERVER_EMAIL = env("SERVER_EMAIL", default="server@saas.com")

# === STRIPE CONFIGURATION ===
# Determina si usar test keys o live keys basado en DEBUG
STRIPE_MODE = "test" if DEBUG else "live"

# Test Keys (Development)
STRIPE_TEST_SECRET_KEY = env("STRIPE_TEST_SECRET_KEY", default="sk_test_changeme")
STRIPE_TEST_PUBLISHABLE_KEY = env("STRIPE_TEST_PUBLISHABLE_KEY", default="pk_test_changeme")
STRIPE_TEST_WEBHOOK_SECRET = env("STRIPE_TEST_WEBHOOK_SECRET", default="whsec_test_changeme")

# Live Keys (Production)
STRIPE_LIVE_SECRET_KEY = env("STRIPE_LIVE_SECRET_KEY", default="")
STRIPE_LIVE_PUBLISHABLE_KEY = env("STRIPE_LIVE_PUBLISHABLE_KEY", default="")
STRIPE_LIVE_WEBHOOK_SECRET = env("STRIPE_LIVE_WEBHOOK_SECRET", default="")

# Seleccionar keys según el modo
if STRIPE_MODE == "test":
    STRIPE_SECRET_KEY = STRIPE_TEST_SECRET_KEY
    STRIPE_PUBLISHABLE_KEY = STRIPE_TEST_PUBLISHABLE_KEY
    STRIPE_WEBHOOK_SECRET = STRIPE_TEST_WEBHOOK_SECRET
else:
    STRIPE_SECRET_KEY = STRIPE_LIVE_SECRET_KEY
    STRIPE_PUBLISHABLE_KEY = STRIPE_LIVE_PUBLISHABLE_KEY
    STRIPE_WEBHOOK_SECRET = STRIPE_LIVE_WEBHOOK_SECRET

# Configurar Stripe con la key seleccionada
import stripe
stripe.api_key = STRIPE_SECRET_KEY

# Configuración de pagos
STRIPE_CURRENCY = env("STRIPE_CURRENCY", default="usd").lower()
STRIPE_SUCCESS_URL = env("STRIPE_SUCCESS_URL", default="http://localhost:3000/success")
STRIPE_CANCEL_URL = env("STRIPE_CANCEL_URL", default="http://localhost:3000/cancel")
STRIPE_WEBHOOK_URL = env("STRIPE_WEBHOOK_URL", default="/api/webhooks/stripe/")

# === REDIS (opcional para Celery) ===
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")

# === LOGGING ===
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {message}",
            "style": "{",
        },
    },
    "filters": {
        "require_debug_false": {
            "()": "django.utils.log.RequireDebugFalse",
        },
        "require_debug_true": {
            "()": "django.utils.log.RequireDebugTrue",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(BASE_DIR, "logs", "django.log"),
            "maxBytes": 1024 * 1024 * 10,  # 10MB
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": env("LOG_LEVEL", default="INFO"),
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "file"],
            "level": env("LOG_LEVEL", default="DEBUG" if DEBUG else "INFO"),
            "propagate": False,
        },
    },
}

# Crear carpeta logs si no existe
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)

# === DRF SPECTACULAR (API DOCS) ===
SPECTACULAR_SETTINGS = {
    "TITLE": "SaaS Backend API",
    "DESCRIPTION": "API REST para plataforma SaaS multi-tenant",
    "VERSION": "1.0.0",
    "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
    "AUTHENTICATION_FLOWS": {
        "bearer": {
            "type": "http",
            "scheme": "bearer",
        },
    },
}
