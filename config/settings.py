import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-local-development-only")
DEBUG = os.getenv("DEBUG", "true").lower() in {"1", "true", "yes", "on"}
if not DEBUG and SECRET_KEY == "django-insecure-local-development-only":
    raise RuntimeError("Set SECRET_KEY before starting with DEBUG=False.")
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "rest_framework", "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular", "operations",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True, "OPTIONS": {"context_processors": ["django.template.context_processors.request", "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DEBUG:
    # Keep developer work isolated from the hosted database, even when DATABASE_URL is present.
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    if not DATABASE_URL:
        raise RuntimeError("Set DATABASE_URL to the production PostgreSQL connection string when DEBUG=False.")
    if "[YOUR-PASSWORD]" in DATABASE_URL or "<" in DATABASE_URL or ">" in DATABASE_URL:
        raise RuntimeError("Replace the DATABASE_URL password placeholder with the real database password before starting with DEBUG=False.")

    import dj_database_url
    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0, ssl_require=True)}
    # Supabase's shared pooler on port 6543 runs in transaction mode and does not support prepared statements.
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": ["operations.authentication.CookieOrHeaderJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle", "rest_framework.throttling.UserRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/hour", "user": "1200/hour", "pricing-estimate": "80/day"},
}
from datetime import timedelta
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=20),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=1),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}
SPECTACULAR_SETTINGS = {
    "TITLE": "Transcitis Courier Operations API", "DESCRIPTION": "Parcel registration, movement, receipt and delivery operations.", "VERSION": "1.0.0", "SERVE_INCLUDE_SCHEMA": False,
    "TAGS": [
        {"name": "Overview", "description": "Dashboard metrics and operational activity."},
        {"name": "Parcels", "description": "Parcel registration, search, status and timeline."},
        {"name": "Trips", "description": "Trip manifests, dispatch and arrival."},
        {"name": "Receiving", "description": "Destination scanning and discrepancy handling."},
        {"name": "Handover", "description": "Pickup and courier delivery PIN verification."},
        {"name": "Exceptions", "description": "Parcel issue review and resolution."},
        {"name": "Stations", "description": "Station directory and operations configuration."},
        {"name": "Authentication", "description": "JWT login, refresh, logout and current staff profile."},
        {"name": "User management", "description": "Staff invitations, station assignments, role permissions and access control."},
        {"name": "Pricing", "description": "Category catalogs, route tariffs, charge estimates and sourced market-value suggestions."},
        {"name": "Receipts", "description": "80 mm thermal receipts with controlled reprints."},
    ],
    "APPEND_COMPONENTS": {"securitySchemes": {"BearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
    "SECURITY": [{"BearerAuth": []}],
}
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend" if os.getenv("EMAIL_HOST_USER") and os.getenv("EMAIL_HOST_PASSWORD") else "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() in {"1", "true", "yes", "on"}
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "Transcitis Operations <no-reply@transcitis.com>")
SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
SECURE_SSL_REDIRECT = os.getenv("SECURE_SSL_REDIRECT", "true" if RENDER_EXTERNAL_HOSTNAME else "false").lower() in {"1", "true", "yes", "on"}
if not DEBUG:
    SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
    CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "2592000")) if SECURE_SSL_REDIRECT else 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL_REDIRECT
    SECURE_CONTENT_TYPE_NOSNIFF = True
