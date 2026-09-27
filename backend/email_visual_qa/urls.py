from django.urls import path

from .views import DesignCritiqueView

urlpatterns = [
    path(
        "critique/",
        DesignCritiqueView.as_view(),
        name="email-design-critique",
    ),
]
