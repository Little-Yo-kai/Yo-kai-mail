from django.urls import path

from .editing import DemoImageUploadView, DemoImageView, DemoRenderView
from .views import DemoGenerateStreamView, DemoGenerateView

urlpatterns = [
    path("render/", DemoRenderView.as_view(), name="phase1-demo-render"),
    path("images/", DemoImageUploadView.as_view(), name="phase1-demo-image-upload"),
    path("assets/<str:cache_key>/", DemoImageView.as_view(), name="phase1-demo-image"),
    path("generate/stream/", DemoGenerateStreamView.as_view(), name="phase1-demo-generate-stream"),
    path(
        "generate/",
        DemoGenerateView.as_view(),
        name="phase1-demo-generate",
    ),
]
