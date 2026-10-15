from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth Endpoints (Login, Logout, Password Reset)
    path('api/auth/token/', TokenObtainPairView.as_view(), name='token-obtain-pair'),
    path('api/auth/token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('api/auth/', include('dj_rest_auth.urls')),

    # Website intelligence
    path('api/website/', include('website_intelligence.urls')),
    path('api/assets/', include('assets.urls')),
    path('api/brand/', include('brand_intelligence.urls')),
    path('api/campaigns/', include('campaigns.urls')),
    path('api/reference-design/', include('reference_design.urls')),
    path('api/reference-library/', include('reference_library.urls')),
    path('api/email-generation/', include('email_generation.urls')),
    path('api/email-rendering/', include('email_rendering.urls')),
    path('api/email-visual-qa/', include('email_visual_qa.urls')),
    path('api/demo/', include('demo_flow.urls')),
    path('api/email-delivery/', include('email_delivery.urls')),

    # API Schema & Documentation Endpoints
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'api/docs/swagger/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui',
    ),
    path(
        'api/docs/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc',
    ),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
