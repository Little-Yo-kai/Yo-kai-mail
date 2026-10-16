import os
from datetime import timedelta
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(DEBUG=(bool, False))
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = env('SECRET_KEY', default='your-fallback-development-secret-key')
DEBUG = env('DEBUG')

ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '[::1]'])


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third-party Packages
    'rest_framework',
    'rest_framework.authtoken',  # Required for dj-rest-auth
    'corsheaders',
    'dj_rest_auth',
    'drf_spectacular',

    # Local apps
    'website_intelligence',
    'assets',
    'brand_intelligence',
    'campaigns',
    'reference_design',
    'reference_library',
    'email_generation',
    'email_rendering',
    'email_visual_qa',
    'email_assets',
    'demo_flow',
    'email_delivery',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',

    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'
WSGI_APPLICATION = 'core.wsgi.application'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
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


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': env.db('DATABASE_URL', default=f'sqlite:///{BASE_DIR / "db.sqlite3"}'),
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

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
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'

# Local asset storage is suitable for development and test environments.
# Production email assets must use an externally reachable HTTPS CDN origin.
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'
ASSET_PUBLIC_BASE_URL = env(
    'ASSET_PUBLIC_BASE_URL',
    default='http://localhost:8000',
)


REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[
    'http://localhost:3000',  # React / Next.js default
    'http://127.0.0.1:3000',
])

FIRECRAWL_API_KEY = env('FIRECRAWL_API_KEY', default='')
# Seconds; the Firecrawl scrape option itself is passed in milliseconds.
FIRECRAWL_REQUEST_TIMEOUT_SECONDS = env.float('FIRECRAWL_REQUEST_TIMEOUT_SECONDS', default=40)
GEMINI_REQUEST_TIMEOUT_SECONDS = env.float('GEMINI_REQUEST_TIMEOUT_SECONDS', default=60)
DEMO_GENERATION_TIMEOUT_SECONDS = env.float('DEMO_GENERATION_TIMEOUT_SECONDS', default=240)
DEMO_MAX_CONCURRENT_GENERATIONS = env.int('DEMO_MAX_CONCURRENT_GENERATIONS', default=4)
DEMO_PREVIEW_TIMEOUT_SECONDS = env.float('DEMO_PREVIEW_TIMEOUT_SECONDS', default=8)
GEMINI_API_KEY = env('GEMINI_API_KEY', default='')
GEMINI_MODEL = env('GEMINI_MODEL', default='gemini-3.8-flash')
GEMINI_REFERENCE_MODEL = env(
    'GEMINI_REFERENCE_MODEL',
    default='gemini-3.1-flash-lite',
)
GEMINI_GENERATION_MODEL = env(
    'GEMINI_GENERATION_MODEL',
    default='gemini-3.8-flash',
)
GEMINI_CRITIC_MODEL = env(
    'GEMINI_CRITIC_MODEL',
    default='gemini-3.1-flash-lite',
)
GEMINI_FALLBACK_MODEL = env(
    'GEMINI_FALLBACK_MODEL',
    default='gemini-3.1-flash-lite',
)
GEMINI_REVISION_MODEL = env(
    'GEMINI_REVISION_MODEL',
    default=GEMINI_GENERATION_MODEL,
)
EMAIL_DESIGN_REVISION_MAX_ATTEMPTS = env.int(
    'EMAIL_DESIGN_REVISION_MAX_ATTEMPTS',
    default=1,
)

MJML_NODE_BINARY = env('MJML_NODE_BINARY', default='node')
EMAIL_SCREENSHOT_EXECUTABLE_PATH = env('EMAIL_SCREENSHOT_EXECUTABLE_PATH', default='')
MJML_COMPILE_TIMEOUT_SECONDS = env.int(
    'MJML_COMPILE_TIMEOUT_SECONDS',
    default=10,
)

RESEND_API_KEY = env('RESEND_API_KEY', default='')
RESEND_FROM_EMAIL = env(
    'RESEND_FROM_EMAIL',
    default='Yo-kai Mail <onboarding@resend.dev>',
)
RESEND_TEST_SEND_ENABLED = env.bool(
    'RESEND_TEST_SEND_ENABLED',
    default=DEBUG,
)

# Production campaign sending is opt-in, even on local development machines.
RESEND_CAMPAIGN_SEND_ENABLED = env.bool(
    'RESEND_CAMPAIGN_SEND_ENABLED',
    default=False,
)
RESEND_WEBHOOK_SECRET = env('RESEND_WEBHOOK_SECRET', default='')

CELERY_BROKER_URL = env(
    'CELERY_BROKER_URL',
    default=env('REDIS_URL', default='redis://127.0.0.1:6379/0'),
)
CELERY_TASK_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TIMEZONE = TIME_ZONE

# Campaign integration gateways. Teammate-owned implementations plug into
# these import paths without creating direct app-to-app model imports.
CAMPAIGN_ASSET_PROMOTION_GATEWAY = env(
    'CAMPAIGN_ASSET_PROMOTION_GATEWAY',
    default='assets.campaign_gateway.CampaignAssetGateway',
)
CAMPAIGN_DESIGN_REVISION_GATEWAY = env(
    'CAMPAIGN_DESIGN_REVISION_GATEWAY',
    default='email_visual_qa.campaign_gateway.CampaignDesignRevisionGateway',
)
CAMPAIGN_AUDIENCE_GATEWAY = env(
    'CAMPAIGN_AUDIENCE_GATEWAY',
    default='email_delivery.campaign_gateway.ContactsAudienceGateway',
)
CAMPAIGN_DELIVERY_GATEWAY = env(
    'CAMPAIGN_DELIVERY_GATEWAY',
    default='email_delivery.campaign_gateway.ResendCampaignDeliveryGateway',
)

EMAIL_ASSET_CACHE_DIR = env(
    'EMAIL_ASSET_CACHE_DIR',
    default=str(BASE_DIR / '.cache' / 'email_assets'),
)
EMAIL_ASSET_CACHE_TTL_SECONDS = env.int(
    'EMAIL_ASSET_CACHE_TTL_SECONDS',
    default=21600,
)
EMAIL_ASSET_MAX_IMAGE_BYTES = env.int(
    'EMAIL_ASSET_MAX_IMAGE_BYTES',
    default=8 * 1024 * 1024,
)
EMAIL_ASSET_MAX_INLINE_BYTES = env.int(
    'EMAIL_ASSET_MAX_INLINE_BYTES',
    default=20 * 1024 * 1024,
)
EMAIL_ASSET_MAX_INLINE_COUNT = env.int(
    'EMAIL_ASSET_MAX_INLINE_COUNT',
    default=10,
)

# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Yo-kai Mail API',
    'DESCRIPTION': 'API documentation for Yo-kai Mail.',
    'VERSION': '0.1.0',
    'SERVE_INCLUDE_SCHEMA': False,
    # File fields have different request/response representations.
    # Splitting them lets Swagger render multipart FileField inputs correctly.
    'COMPONENT_SPLIT_REQUEST': True,
    'ENUM_NAME_OVERRIDES': {
        'CampaignStatusEnum': 'campaigns.models.CampaignStatus.choices',
        'CampaignTransitionStatusEnum': ['reviewed', 'ready'],
        'ContactStatusEnum': 'email_delivery.models.ContactStatus.choices',
        'ConsentStatusEnum': 'email_delivery.models.ConsentStatus.choices',
    },
}
