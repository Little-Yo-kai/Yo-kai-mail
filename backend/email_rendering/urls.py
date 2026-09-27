from django.urls import path

from .views import EmailScreenshotView, HTMLRenderView, MJMLRenderView

urlpatterns = [
    path("mjml/", MJMLRenderView.as_view(), name="email-render-mjml"),
    path("html/", HTMLRenderView.as_view(), name="email-render-html"),
    path(
        "screenshot/",
        EmailScreenshotView.as_view(),
        name="email-render-screenshot",
    ),
]
