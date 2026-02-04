from pathlib import Path
import os
from corsheaders.defaults import default_headers


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

    'dj_rest_auth',
    'dj_rest_auth.registration',
    'django_filters',

    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.google",
    # "captcha",
    'django_crontab',
    
    'django_countries',
    'channels',
    'aryuapp',
    'live_quiz',
    "axes",
    "mock_interview",
    "webinar",
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
            "hosts": [
                "redis://aryu_user:35l1VUx9@49.207.178.161:6379/0",
            ],
        },
    },
}


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

    # custom middlewares AFTER auth + allauth
    "aryuapp.middleware.AutoLogoutMiddleware",
    "aryuapp.middleware.DBCleanupMiddleware",

    # Axes AFTER AuthenticationMiddleware
    "axes.middleware.AxesMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'aryuapp.auth.CustomJWTAuthentication',
    ],
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend'
    ],
    'EXCEPTION_HANDLER': 'aryuapp.exceptions.custom_exception_handler',
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
    "https://portal.aryuacademy.com",
    "https://workshop.aryuacademy.com",
]

CSRF_TRUSTED_ORIGINS = [
    "https://portal.aryuacademy.com",
    "https://workshop.aryuacademy.com",
]

ALLOWED_HOSTS = [
    "portal.aryuacademy.com",
    "workshop.aryuacademy.com",
]  # Allow all hosts for development; change in production


ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = True

RAZORPAY_KEY_ID = "rzp_test_RWUNL3DPw8Kmwk"
RAZORPAY_KEY_SECRET = "EhBVN3O6o1BMc2sQANsXXlzI"

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

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.hostinger.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "info@aryuacademy.com"
EMAIL_HOST_PASSWORD = "SgSVEp?ev5|"
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


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


MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

MEDIA_BASE_URL = "https://aylms.aryuprojects.com/api"

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'aylms_live',  
        'USER': 'aylms_live',
        'PASSWORD':'KfdW543FDdfg',
        'HOST': '69.62.78.109',   
        'PORT': '5432',  
        'AUTOCOMMIT': True,
        'CONN_MAX_AGE': 60,
    },
}

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

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

ROOT_URLCONF = 'Aryu.urls'

AUTH_USER_MODEL = 'aryuapp.User'

WSGI_APPLICATION = 'Aryu.wsgi.application'

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')