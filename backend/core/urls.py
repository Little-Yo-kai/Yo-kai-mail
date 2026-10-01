from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
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

    # Asset pipeline
    path('api/assets/', include('assets.urls')),

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
    # Local/dev only - LocalStorageAdapter's URLs resolve through this.
    # Production won't route large media traffic through Django itself
    # (the S3/R2 adapter serves directly from the bucket/CDN instead).
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)