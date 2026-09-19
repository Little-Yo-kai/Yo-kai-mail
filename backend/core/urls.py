from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    path('admin/', admin.site.urls),

    # Auth Endpoints (Login, Logout, Password Reset)
    path('api/auth/', include('dj_rest_auth.urls')),

    # Website intelligence
    path('api/website/', include('website_intelligence.urls')),
    path('api/brand/', include('brand_intelligence.urls')),

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
