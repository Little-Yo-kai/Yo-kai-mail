from django.urls import path

from .views import ReferenceDesignAnalyzeView

urlpatterns = [
    path("analyze/", ReferenceDesignAnalyzeView.as_view(), name="reference-design-analyze"),
]
