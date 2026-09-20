from django.urls import path

from .views import HTMLRenderView, MJMLRenderView

urlpatterns = [
    path("mjml/", MJMLRenderView.as_view(), name="email-render-mjml"),
    path("html/", HTMLRenderView.as_view(), name="email-render-html"),
]
