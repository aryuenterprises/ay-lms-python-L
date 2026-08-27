
from datetime import timedelta
from corsheaders.defaults import default_headers
from pathlib import Path
import os
import sys
from dotenv import load_dotenv
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR.parent / ".env")

TURNSTILE_SECRET_KEY = os.getenv("TURNSTILE_SECRET_KEY")

CORS_ALLOW_HEADERS = list(default_headers) + [
    'access-control-allow-origin',
    'authorization',
    'content-type',
]


"""
pip install channels-redis paypalrestsdk reportlab pyclamd pytesseract Pillow django_countries django_filter dj_rest_auth django-cors-headers django-allauth channels psycopg2-binary pytz stripe twilio holidays razorpay num2words djangorestframework Django qrcode django_redis django-axes captcha django_crontab 
"""


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-e-ar=#hq&(q0ujnwofc!%8#in(2z1osso65+(8i+&elo=cn4$k'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Application definition

INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',  # Required by django-allauth

    'rest_framework',
    'rest_framework.authtoken',
    "rest_framework_simplejwt.token_blacklist",

    'dj_rest_auth',
    'dj_rest_auth.registration',
    'django_filters',

    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.google",
    "rest_framework_simplejwt",
    # "captcha",
    'django_crontab',
    'django.contrib.postgres',
    "django_celery_beat",
    "drf_spectacular",
    
    'django_countries',
    'channels',
    'aryuapp',
    'live_quiz',
    "axes",
    "mock_interview",
    "webinar",
    "announcements",
    "chats",
    "tests",
    "feedback",
    "courses",
    "core",
    "batches",
    "payments",
    "ebook",
    "resume",
    "resources",
    "lead",
    "reports",
    "lead.whatsapp",
    "code_assessment",
    
]

ASGI_APPLICATION = "Aryu.asgi.application"

RECAPTCHA_PUBLIC_KEY = '6Ld5EyEsAAAAAMsQJ-ioz2ZRzgAsgbfjFIHcT3Hl'
RECAPTCHA_PRIVATE_KEY = '6Ld5EyEsAAAAAPhz1O4n51_Ee9P6IyyRfLkHBTVQ'
RECAPTCHA_REQUIRED_SCORE = 0.5

ZOOM_ACCOUNT_ID="qbm5JdFXT5Kd6vQS3q-bBA"
ZOOM_CLIENT_ID="sNGZ9uK7QNa8zOQOjHpeHg"
ZOOM_CLIENT_SECRET="XjdXCI6uS8R9e2Qr903HrA28TpZe55V4"
ZOOM_TOKEN="7oD_nvdHT3Cia3ChbahPLw"

# CACHES = {
#     "default": {
#         "BACKEND": "django.core.cache.backends.redis.RedisCache",
#         "LOCATION": "redis://127.0.0.1:6379/1",
#     }
# }


# CHANNEL_LAYERS = {
#     "default": {
#         "BACKEND": "channels_redis.core.RedisChannelLayer",
#         "CONFIG": {
#             "hosts": [("127.0.0.1", 6379)],
#         },
#     },
# }

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://:35l1VUx9@49.207.178.161:6379/0",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        }
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": ["redis://:35l1VUx9@49.207.178.161:6379/1"],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

# CELERY_BROKER_URL = "redis://127.0.0.1:6379/2"
# CELERY_RESULT_BACKEND = "redis://127.0.0.1:6379/4"

CELERY_BROKER_URL = "redis://:35l1VUx9@49.207.178.161:6379/3"
CELERY_RESULT_BACKEND = "redis://:35l1VUx9@49.207.178.161:6379/5"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = "Asia/Kolkata"
CELERY_ENABLE_UTC = False
CELERY_TASK_TIME_LIMIT = 1800
CELERY_TASK_SOFT_TIME_LIMIT = 1500
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",

    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",

    # CSRF must come *before* AuthenticationMiddleware
    "django.middleware.csrf.CsrfViewMiddleware",


    # Authentication
    "django.contrib.auth.middleware.AuthenticationMiddleware",

    # Allauth must come immediately after AuthenticationMiddleware
    "allauth.account.middleware.AccountMiddleware",

    "core.middleware.security_sanitizer.InputSanitizationMiddleware",

    # custom middlewares AFTER auth + allauth
    "aryuapp.middleware.AutoLogoutMiddleware",
    "aryuapp.middleware.DBCleanupMiddleware",

    # Axes AFTER AuthenticationMiddleware
    "axes.middleware.AxesMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


REST_FRAMEWORK = {

    # AUTHENTICATION

    "DEFAULT_AUTHENTICATION_CLASSES": [
        "aryuapp.auth.CustomJWTAuthentication",
    ],

    # PERMISSIONS

    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],

    'NUM_PROXIES': 1,

    # FILTERS

    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],

    # EXCEPTION HANDLER

    "EXCEPTION_HANDLER":
        "aryuapp.exceptions.custom_exception_handler",

    # THROTTLING

    "DEFAULT_THROTTLE_CLASSES": [

        # Public APIs
        "rest_framework.throttling.AnonRateThrottle",

        # Authenticated APIs
        "rest_framework.throttling.UserRateThrottle",
    ],

    "DEFAULT_THROTTLE_RATES": {

        # =============================================
        # DEFAULT
        # =============================================

        "anon": "20/min",
        "user": "2000/min",

        # =============================================
        # CUSTOM SCOPES
        # =============================================

        # Lead Admin APIs
        "admin_lead": "3000/min",

        # Public Lead Submission
        "public_lead": "60/min",

        # Login Protection
        "login": "10/min",

        # OTP APIs
        "otp": "5/min",

        # AI APIs
        "ai": "30/min",
    },

    # PAGINATION

    "DEFAULT_PAGINATION_CLASS":
        "rest_framework.pagination.PageNumberPagination",

    "PAGE_SIZE": 25,

    # RENDERERS

    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],

    # PARSERS

    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],

    # SECURITY

    "DEFAULT_VERSIONING_CLASS":
        "rest_framework.versioning.NamespaceVersioning",

    "DEFAULT_SCHEMA_CLASS":
        "drf_spectacular.openapi.AutoSchema",
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

PDF_MAX_HTML_BYTES = 10 * 1024 * 1024


SIMPLE_JWT = {

    # access token short life
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),

    # refresh token long life
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),

    # generate new refresh token every refresh
    "ROTATE_REFRESH_TOKENS": True,

    # blacklist old refresh tokens
    "BLACKLIST_AFTER_ROTATION": True,

    # update last login
    "UPDATE_LAST_LOGIN": True,

    "ALGORITHM": "HS256",

    "SIGNING_KEY": SECRET_KEY,

    "AUTH_HEADER_TYPES": ("Bearer",),

}

SOCIALACCOUNT_PROVIDERS = {
    "github": {
        "SCOPE": ["user:email"],
        "VERIFIED_EMAIL": True,
        "APP": {
            "client_id": "Ov23liv2hQNjYO3xLdwn",
            "secret": "c022f82b1ba78bff67ea1ceafb623a9c3b6afd82",
            "key": "",
        }
    },
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "APP": {
            "client_id": "454548779156-ntr8e0vv52001oiejk0ee3knggtula8m.apps.googleusercontent.com",
            "secret": "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",
            "key": "",
        },
    },
}

FASTAPI_URL="https://ai.aryuacademy.com"

TELECRM_TOKEN="2b5fa0b5-b45c-4150-ab6f-09a001575ca01779800797507:0d16d31d-e820-45fa-aafc-869ef640917d"
TELECRM_ID="6a13da730fbcb752673e080c"
TELECRM_API = "https://next-api.telecrm.in"



SERVER_ROOT = Path("/var/www/ay-lms-python-L") if Path("/var/www/ay-lms-python-L/logs").exists() else BASE_DIR.parent
# SERVER_ROOT = Path("/home/aryu_user/Arun/ay-lms-python-L") if Path("/home/aryu_user/Arun/ay-lms-python-L/logs").exists() else BASE_DIR.parent
# SERVER_ROOT = Path("/var/www/python-staging") if Path("/var/www/python-staging/logs").exists() else BASE_DIR.parent

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "formatters": {
        "simple": {
            "format": "[{levelname}] {asctime} {name} :: {message}",
            "style": "{",
        },
        "verbose": {
            "format": "[{levelname}] {asctime} {name} :: {message}",
            "style": "{",
        },
    },

    "handlers": {
        "webhook_file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": SERVER_ROOT / "logs" / "razorpay_webhook.log",
            "formatter": "verbose",
        },
        "general_file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": SERVER_ROOT / "logs" / "general.log",
            "formatter": "verbose",
        },
        "whatsapp_file": {
            "level": "DEBUG",
            "class": "logging.FileHandler",
            "filename": SERVER_ROOT / "logs" / "whatsapp.log",
            "formatter": "verbose",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },

    "loggers": {
        # Razorpay logger only
        "razorpay_webhook": {
            "handlers": ["webhook_file"],
            "level": "DEBUG",
            "propagate": False,
        },

        "general": {
            "handlers": ["general_file", "console"],  # Logs to file AND terminal
            "level": "DEBUG",                          # Ensures logger.debug() writes to the file
            "propagate": False,
        },

        "whatsapp": {
            "handlers": ["whatsapp_file", "console"],  # Logs to file AND terminal
            "level": "DEBUG",                          # Ensures logger.debug() writes to the file
            "propagate": False,
        },

        # Everything else
        "": {
            "handlers": ["console"],
            "level": "INFO",
        },
    },
}

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]


TEST_KEY_ID = "rzp_test_S1jkEo5h7lkTeU"
TEST_SECRET_KEY = "FiVzu8TnYUPFnMH1Xc1VMxh7"

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # hours

AXES_LOCKOUT_PARAMETERS = ['ip_address', 'username']

SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_EMAIL_VERIFICATION = "none"

SOCIALACCOUNT_QUERY_EMAIL = True
ACCOUNT_ADAPTER = "aryuapp.adapters.MyAccountAdapter"
SOCIALACCOUNT_ADAPTER = "aryuapp.adapters.MySocialAccountAdapter"

CRONJOBS = [
    ('0 0 * * *', 'aryuapp.management.commands.deactivate_students.Command.handle'),
]

# CORS_ALLOW_ALL_ORIGINS = True

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://workshop.aryuacademy.com",
    "https://webminar.aryuprojects.com",
    "https://airesumebuilder.aryuacademy.com",
    "https://passats.aryuacademy.com",
    "https://aryuacademy.com",
    "https://aylms.aryuprojects.com",
    "https://ayanew.aryuprojects.com",
    "https://aylms.aryuprojects.com",
]

CSRF_TRUSTED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:8000",
    "https://workshop.aryuacademy.com",
    "https://webminar.aryuprojects.com",
    "https://airesumebuilder.aryuacademy.com",
    "https://passats.aryuacademy.com",
    "https://aryuacademy.com",
    "https://aylms.aryuprojects.com",
    "https://ayanew.aryuprojects.com",
    "https://aylms.aryuprojects.com",

]

ALLOWED_HOSTS = [
    "workshop.aryuacademy.com",
    "localhost",
    "webminar.aryuprojects.com",
    "airesumebuilder.aryuacademy.com",
    "passats.aryuacademy.com",
    "aryuacademy.com",
    "127.0.0.1",
    "aylms.aryuprojects.com",
    "ayanew.aryuprojects.com",
    "aylms.aryuprojects.com",
]  # Allow all hosts for development; change in production


# LOCAL DEVELOPMENT:
KAFKA_BOOTSTRAP_SERVERS = "localhost:9092"

# PRODUCTION (Using Server IP):
# KAFKA_BOOTSTRAP_SERVERS = "192.168.1.150:9092"

# PRODUCTION (Using Domain/DNS Name):
# KAFKA_BOOTSTRAP_SERVERS = "kafka.yourdomain.com:9092"

ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True

RAZORPAY_KEY_ID = "rzp_live_SKfiZYRJEe8WuU"
RAZORPAY_KEY_SECRET = "Du4L7ebKchXQSOMcgzx5wE3h"

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = list(default_headers) + [
    'X-CSRFToken',
]
CORS_EXPOSE_HEADERS = ['Content-Type', 'X-CSRFToken']

CORS_ALLOW_METHODS = (
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
)

# EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
# DEFAULT_FROM_EMAIL = 'support@aryuacademy.com'
# EMAIL_HOST = "smtp.hostinger.com"
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = "support@aryuacademy.com"
# EMAIL_HOST_PASSWORD = "A/cMu5nqYs16"
# DEFAULT_FROM_EMAIL = "Aryu Academy <support@aryuacademy.com>"
# settings.py

# settings.py

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.hostinger.com"
EMAIL_PORT = 465
EMAIL_USE_SSL = True
EMAIL_USE_TLS = False
EMAIL_HOST_USER = "support@aryuacademy.com"
EMAIL_HOST_PASSWORD = "A/cMu5nqYs16"
DEFAULT_FROM_EMAIL = "support@aryuacademy.com"
SUPPORT_EMAIL = "support@aryuacademy.com"


SITE_ID = 1

if DEBUG:
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_SAMESITE = "Lax"

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"


SESSION_COOKIE_AGE = 1800  # 30 minutes in seconds
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

GOOGLE_CLIENT_ID = "1004056077681-qfeuc4edcpob49o1gk4168a3ap7lrnqs.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
GOOGLE_REDIRECT_URI = "http://127.0.0.1:8000/api/oauth2callback/"


ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_EMAIL_VERIFICATION = 'mandatory'
ACCOUNT_CONFIRM_EMAIL_ON_GET = True

ROOT_URLCONF = 'Aryu.urls'

AUTH_USER_MODEL = 'aryuapp.User'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': ['templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

SECURE_SSL_REDIRECT = False

TWILIO_SID = "AC5ec75a85985e84acbe9bfa7a240d6386"
TWILIO_AUTH_TOKEN = "44fbdfc9f0960b464c20a193b797c7f7"
TWILIO_PHONE_NUMBER = "+15075854260"


MEDIA_URL = 'media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'api/media')

MEDIA_BASE_URL = "https://aylms.aryuprojects.com/api"

# class DisableMigrations:
#     def __getitem__(self, item):
#         return None
#     def __contains__(self, item):
#         return True

# if 'test' in sys.argv:
#     import django.contrib.postgres.fields
#     import django.db.models
#     from django.db.backends.sqlite3.schema import DatabaseSchemaEditor

#     class DummyArrayField(django.db.models.JSONField):
#         def __init__(self, *args, **kwargs):
#             kwargs.pop('base_field', None)
#             kwargs.pop('size', None)
#             super().__init__(*args, **kwargs)

#     django.contrib.postgres.fields.ArrayField = DummyArrayField

#     orig_quote_name = DatabaseSchemaEditor.quote_name
#     def safe_quote_name(self, name):
#         if "." in name:
#             name = name.split(".")[-1].strip('"')
#         return orig_quote_name(self, name)
#     DatabaseSchemaEditor.quote_name = safe_quote_name

#     DATABASES = {
#         'default': {
#             'ENGINE': 'django.db.backends.sqlite3',
#             'NAME': ':memory:',
#         }
#     }
#     MIGRATION_MODULES = DisableMigrations()
# else:
#     DATABASES = {
#         'default': {
#             'ENGINE': 'django.db.backends.postgresql',
#             'NAME': 'aylms_live',  
#             'USER': 'aylms_live',
#             'PASSWORD':'KfdW543FDdfg',
#             'HOST': '187.127.178.144',   
#             'PORT': '5432',  
#             'AUTOCOMMIT': True,
#             'CONN_MAX_AGE': 60,
#         },
#     }

class DisableMigrations:
    def __getitem__(self, item):
        return None
    def __contains__(self, item):
        return True

if 'test' in sys.argv:
    import django.contrib.postgres.fields
    import django.db.models
    from django.db.backends.sqlite3.schema import DatabaseSchemaEditor

    class DummyArrayField(django.db.models.JSONField):
        def __init__(self, *args, **kwargs):
            kwargs.pop('base_field', None)
            kwargs.pop('size', None)
            super().__init__(*args, **kwargs)

    django.contrib.postgres.fields.ArrayField = DummyArrayField

    orig_quote_name = DatabaseSchemaEditor.quote_name
    def safe_quote_name(self, name):
        if "." in name:
            name = name.split(".")[-1].strip('"')
        return orig_quote_name(self, name)
    DatabaseSchemaEditor.quote_name = safe_quote_name

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }
    MIGRATION_MODULES = DisableMigrations()
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': 'aylms_live',  
            'USER': 'aylms_live',
            'PASSWORD':'KfdW543FDdfg',
            'HOST': '187.127.178.144',   
            'PORT': '5432',  
            'AUTOCOMMIT': True,
            'CONN_MAX_AGE': 60,
            'OPTIONS': {
                'options': '-c search_path=livequiz,public'
            }
        },
    }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'aylms_live',
#         'USER': 'aylms_live',
#         'PASSWORD': 'KfdW543FDdfg',
#         'HOST': '187.127.178.144',
#         'PORT': '5432',
#         'AUTOCOMMIT': True,
#         'CONN_MAX_AGE': 60,
#     },
# }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'aylms_live',
#         'USER': 'aylms_live',
#         'PASSWORD': 'KfdW543FDdfg',
#         'HOST': '187.127.178.144',
#         'PORT': '5432',
#         'AUTOCOMMIT': True,
#         'CONN_MAX_AGE': 60,
#     },
# }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'academy_management_staging',
#         'USER': 'academy_user',
#         'PASSWORD':'c2lC47v',
#         'HOST': '69.62.78.109',
#         'PORT': '5432',
#         'AUTOCOMMIT': True,
#         'CONN_MAX_AGE': 60,
#         'OPTIONS': {
#             'options': '-c search_path=livequiz,public'
#         }
#     },
# }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'academy_staging',
#         'USER': 'aryu_user',
#         'PASSWORD':'YUra@2025',
#         'HOST': '49.207.178.161',
#         'PORT': '5432',
#         'AUTOCOMMIT': True,
#         'CONN_MAX_AGE': 60,
#         'OPTIONS': {
#             'options': '-c search_path=livequiz,public'
#         }
#     },
# }

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.postgresql',
#         'NAME': 'academy_management',  
#         'USER': 'postgres',
#         'PASSWORD':'akzworld',
#         'HOST': 'localhost',
#         'PORT': '5432',  
#         'AUTOCOMMIT': True,
#         'OPTIONS': {
#             'options': '-c search_path=livequiz,public'
#         }
#     }
# }



# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'Asia/Kolkata'

FRONTEND_URL = 'https://aylms.aryuprojects.com'
PORTAL_FRONTEND_URL = FRONTEND_URL
SITE_URL = FRONTEND_URL

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

BASE_DIR = Path(__file__).resolve().parent.parent

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")

STATIC_URL = 'aryuapp/static/'
STATICFILES_DIRS = [
    BASE_DIR / "aryuapp/static",
]

MEDIA_URL = "media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

ROOT_URLCONF = 'Aryu.urls'

AUTH_USER_MODEL = 'aryuapp.User'

WSGI_APPLICATION = 'Aryu.wsgi.application'

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
