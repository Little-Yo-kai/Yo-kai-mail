from django.urls import path

from .views import DemoGenerateStreamView, DemoGenerateView

urlpatterns = [
    path("generate/stream/", DemoGenerateStreamView.as_view(), name="phase1-demo-generate-stream"),
    path(
        "generate/",
        DemoGenerateView.as_view(),
        name="phase1-demo-generate",
    ),
]
