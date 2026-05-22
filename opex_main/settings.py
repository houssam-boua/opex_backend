# opex_main/settings.py
import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from django.core.exceptions import ImproperlyConfigured

# Load .env file
load_dotenv()

BASE_DIR   = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")
DEBUG      = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = (
    os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if os.environ.get("CSRF_TRUSTED_ORIGINS")
    else []
)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "False") == "True"
CSRF_COOKIE_SECURE = os.environ.get("CSRF_COOKIE_SECURE", "False") == "True"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    "channels",
    "storages",
    "django_celery_beat",
    # Core SaaS
    "core",
    "accounts",
    "billing",
    "shared",
    "analytics",
    "reports",
    # 18 Modules OPEX
    "modules.gemba",
    "modules.audits",
    "modules.iso9001",
    "modules.five_s",
    "modules.tpm",
    "modules.lean_flow",
    "modules.vsm",
    "modules.smed",
    "modules.sfm",
    "modules.rotation_table",
    "modules.capa",
    "modules.risk",
    "modules.problem_solving",
    "modules.poka_yoke",
    "modules.skills",
    "modules.visual_management",
    "modules.routines",
    "modules.messaging",
]

AUTH_USER_MODEL = "accounts.CustomUser"

AUTHENTICATION_BACKENDS = [
    "accounts.backends.TenantEmailBackend",
]

# FIX V3: email is unique per (tenant, email), NOT globally.
# Django's auth.E003 check requires USERNAME_FIELD to be globally unique,
# but our multi-tenant architecture intentionally uses a composite constraint.
SILENCED_SYSTEM_CHECKS = ["auth.W004"]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "opex_main.middleware.tenant_middleware.TenantMiddleware",
    "opex_main.middleware.subscription_middleware.SubscriptionMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "opex_main.urls"
ASGI_APPLICATION = "opex_main.asgi.application"
WSGI_APPLICATION = "opex_main.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
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

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     os.environ.get("DB_NAME",     "opex"),
        "USER":     os.environ.get("DB_USER",     "postgres"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "postgres"),
        "HOST":     os.environ.get("DB_HOST",     "localhost"),
        "PORT":     os.environ.get("DB_PORT",     "5432"),
    }
}

REDIS_URL = os.environ.get("REDIS_URL")
if not DEBUG and not REDIS_URL:
    raise ImproperlyConfigured("REDIS_URL is required in production for Celery and WebSockets")
REDIS_URL = REDIS_URL or "redis://localhost:6379/0"

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG":  {"hosts": [REDIS_URL]},
    }
}

# Celery
CELERY_BROKER_URL     = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT     = ["json"]
CELERY_TASK_SERIALIZER    = "json"
CELERY_RESULT_SERIALIZER  = "json"
CELERY_TIMEZONE           = "Europe/Paris"
CELERY_BEAT_SCHEDULER     = "django_celery_beat.schedulers:DatabaseScheduler"

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "200/minute",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "OPEX API",
    "DESCRIPTION": "Plateforme d'Excellence Opérationnelle — API Backend",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS   = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")

# Email
EMAIL_BACKEND       = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST          = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT          = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL  = "noreply@opex.app"

# Fichiers — S3 / MinIO (conditionnel : si pas de clé, stockage local)
AWS_ACCESS_KEY_ID       = os.environ.get("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY   = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_BUCKET", "opex-files")
AWS_S3_ENDPOINT_URL     = os.environ.get("AWS_S3_ENDPOINT_URL", "")
if AWS_ACCESS_KEY_ID:
    DEFAULT_FILE_STORAGE = "storages.backends.s3boto3.S3Boto3Storage"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE     = "Europe/Paris"
USE_I18N      = True
USE_TZ        = True

STATIC_URL  = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL   = "/media/"
MEDIA_ROOT  = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "WARNING"),
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": os.environ.get("DJANGO_LOG_LEVEL", "WARNING"),
            "propagate": False,
        },
        "celery": {
            "handlers": ["console"],
            "level": os.environ.get("CELERY_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
        "opex": {
            "handlers": ["console"],
            "level": os.environ.get("OPEX_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}
