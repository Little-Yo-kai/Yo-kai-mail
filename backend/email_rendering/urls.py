from django.urls import path

from .views import MJMLRenderView

urlpatterns = [
    path("mjml/", MJMLRenderView.as_view(), name="email-render-mjml"),
]
