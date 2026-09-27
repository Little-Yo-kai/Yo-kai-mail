from django.urls import path

from .views import DemoGenerateView

urlpatterns = [
    path(
        "generate/",
        DemoGenerateView.as_view(),
        name="phase1-demo-generate",
    ),
]
