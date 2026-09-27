from django.urls import path

from .views import BrandAnalyzeView

urlpatterns = [
    path("analyze/", BrandAnalyzeView.as_view(), name="brand-analyze"),
]
