"""Django settings for the notes service.

Every environment-specific value is read from environment variables, so one
image (one SHA-256 digest) can be promoted from staging to production unchanged.
"""

import os
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

# Project root (the folder that contains manage.py).
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers for reading environment variables
# ---------------------------------------------------------------------------
def env(name: str, default: str | None = None) -> str:
    """Return env var `name`, or `default`.

    With default=None the variable is REQUIRED: if it is missing we raise at
    startup. A misconfigured pod then crashes immediately (fail fast) instead
    of starting and breaking on the first real request.
    """
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Environment variable {name} is required")
    return value


def env_bool(name: str, default: bool = False) -> bool:
    """Env vars are always strings, and the string "false" is truthy in Python.
    This turns "1/true/yes/on" into True and everything else into False."""
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    """ "a.com, b.com" -> ["a.com", "b.com"]; empty items are dropped."""
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


def parse_database_url(url: str) -> dict:
    """Turn one DATABASE_URL into Django's DATABASES dict.

    postgres://notes:secret@db.example:5432/notes?sslmode=require
    └scheme┘  └user┘└pass┘ └──host───┘ └port┘└name┘└─options──┘

    sqlite:///db.sqlite3        -> relative to BASE_DIR (local dev, unit tests)
    sqlite:////abs/path.db      -> absolute path (note the 4 slashes)
    """
    parsed = urlparse(url)

    if parsed.scheme == "sqlite":
        path = parsed.path[1:]  # drop the "/" that separates the (empty) host from the path
        return {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": path if path.startswith("/") else BASE_DIR / path,
        }

    if parsed.scheme in {"postgres", "postgresql"}:
        return {
            # The normal Postgres backend wrapped by django-prometheus, so query
            # counts/latency appear on /metrics (used in Module 13).
            "ENGINE": "django_prometheus.db.backends.postgresql",
            "NAME": unquote(parsed.path.lstrip("/")),
            # unquote() decodes URL-escaped characters, e.g. "%40" -> "@" in passwords.
            "USER": unquote(parsed.username or ""),
            "PASSWORD": unquote(parsed.password or ""),
            "HOST": parsed.hostname or "",
            "PORT": str(parsed.port or 5432),
            # ?sslmode=require&connect_timeout=5 -> {"sslmode": "require", ...}
            "OPTIONS": dict(parse_qsl(parsed.query)),
            # Reuse a connection for 60 s instead of opening one per request.
            "CONN_MAX_AGE": 60,
            # Test a reused connection before use, so a DB restart doesn't
            # cause a burst of errors from dead connections.
            "CONN_HEALTH_CHECKS": True,
        }

    raise ImproperlyConfigured(f"Unsupported DATABASE_URL scheme: {parsed.scheme!r}")


# ---------------------------------------------------------------------------
# Environment and security
# ---------------------------------------------------------------------------
# Which environment this process runs in: dev | ci | staging | prod.
# Used in logs and in the S3 export key; never used to switch code paths.
APP_ENV = env("APP_ENV", "dev")

# Debug pages leak source code and settings. On by default ONLY in dev.
DEBUG = env_bool("DEBUG", APP_ENV == "dev")

# Signs sessions, CSRF tokens and password-reset links.
# Only dev gets a fallback; in staging/prod default=None makes it REQUIRED,
# so a missing key crashes startup instead of running with a public key.
# In Module 7 the real value comes from a Kubernetes Secret.
SECRET_KEY = env("SECRET_KEY", "dev-insecure-key" if APP_ENV == "dev" else None)

# Django rejects requests whose Host header is not listed (Host-header attacks).
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")

# Needed for the admin login form when served over HTTPS behind an ingress,
# e.g. "https://notes.staging.example".
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # Must come BEFORE staticfiles: makes `runserver` serve static files the
    # same way production does (via WhiteNoise), so dev behaves like prod.
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django_prometheus",  # /metrics endpoint + request/DB metrics
    "notes",  # our app
]

# Middleware runs TOP->BOTTOM on the request and BOTTOM->TOP on the response.
MIDDLEWARE = [
    # FIRST: starts the timer before anything else, so latency covers everything.
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Right after Security: serves /static/ and returns early, before sessions
    # and auth run. Fast, and no nginx container needed.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # LAST: records final status code and total latency of the response.
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # project-wide templates folder
        "APP_DIRS": True,  # also look in <app>/templates/
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Entry point gunicorn will load in the container: `gunicorn config.wsgi`.
WSGI_APPLICATION = "config.wsgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# Local default is SQLite; staging/prod set DATABASE_URL=postgres://...
DATABASES = {"default": parse_database_url(env("DATABASE_URL", "sqlite:///db.sqlite3"))}

# 64-bit primary keys: no overflow surprises when the table grows.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True  # store datetimes in UTC; convert only for display


# ---------------------------------------------------------------------------
# Static files (CSS/JS for the admin)
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
# `collectstatic` copies all static files here. We run it in the Docker build
# (Module 3), so the files are baked into the image.
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Writes gzip/brotli versions and adds a content hash to each file name
    # (app.css -> app.3f2a9c.css). Browsers can cache forever, and a new
    # deploy can never serve a stale file.
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


# ---------------------------------------------------------------------------
# AWS / S3 export
# ---------------------------------------------------------------------------
# Locally: http://localhost:4566 -> boto3 talks to Floci.
# Real AWS: leave unset -> None -> boto3 uses the real AWS endpoints.
# No access keys here: boto3 finds credentials itself (env vars locally,
# temporary IRSA/OIDC credentials in the cluster — Module 5).
AWS_ENDPOINT_URL = os.environ.get("AWS_ENDPOINT_URL") or None
AWS_REGION = env("AWS_REGION", env("AWS_DEFAULT_REGION", "us-east-1"))
EXPORT_BUCKET = env("EXPORT_BUCKET", "notes-export")


# ---------------------------------------------------------------------------
# Production-only hardening
# ---------------------------------------------------------------------------
if not DEBUG:
    # TLS ends at the ingress; Django receives plain HTTP plus the header
    # X-Forwarded-Proto: https. Trust it so request.is_secure() is correct
    # and redirects use https://.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # Browsers send these cookies only over HTTPS.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Containers log to STDOUT, never to files. Kubernetes collects stdout and
# Module 13 ships it to the log stack. LOG_LEVEL changes without a rebuild.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,  # keep Django's own loggers working
    "formatters": {
        "plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "plain"},
    },
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}
