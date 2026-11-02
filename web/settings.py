"""Django settings for Sarah chat UI."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ON_RENDER = bool(os.environ.get("RENDER"))
_debug_raw = os.environ.get("DJANGO_DEBUG", "").strip().lower()
if _debug_raw in {"0", "false", "no"}:
    DEBUG = False
elif _debug_raw in {"1", "true", "yes"}:
    DEBUG = True
else:
    DEBUG = not ON_RENDER

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or os.environ.get("SECRET_KEY") or ""
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-only-django-secret-not-for-production"
    else:
        raise RuntimeError("DJANGO_SECRET_KEY is required when DEBUG is False")

allowed = [h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()]
if DEBUG and not allowed:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = allowed or ["localhost", "127.0.0.1"]
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_host and render_host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(render_host)
    if ".onrender.com" not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(".onrender.com")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

# Lightweight identities live in a signed (tamper-proof) cookie — no DB migrations.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 180
SESSION_SERIALIZER = "django.contrib.sessions.serializers.JSONSerializer"

ROOT_URLCONF = "web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "chat" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "web.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "web" / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
WHITENOISE_USE_FINDERS = DEBUG

FASTAPI_BASE_URL = os.environ.get("FASTAPI_BASE_URL", "http://127.0.0.1:8001")
DEFAULT_PERSONA_ID = os.environ.get("DEFAULT_PERSONA_ID", "sarah_taylor_001")
DEFAULT_USER_ID = os.environ.get("DEFAULT_USER_ID", "local-user")
# Must match FastAPI. Falls back to the same dev constant as persona_runtime.config.
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN") or "dev-internal-token-change-me"
if not DEBUG and INTERNAL_API_TOKEN == "dev-internal-token-change-me":
    raise RuntimeError("INTERNAL_API_TOKEN is required when DEBUG is False")
MAX_USERS_PER_BROWSER = int(os.environ.get("MAX_USERS_PER_BROWSER", "25"))

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

csrf_origins = [
    o.strip().rstrip("/")
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]
render_url = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
if render_url and render_url not in csrf_origins:
    csrf_origins.append(render_url)
CSRF_TRUSTED_ORIGINS = csrf_origins

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
