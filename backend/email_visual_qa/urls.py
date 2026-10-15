from django.urls import path

from .views import DesignCritiqueView, DesignRevisionView

urlpatterns = [
    path(
        "critique/",
        DesignCritiqueView.as_view(),
        name="email-design-critique",
    ),
    path(
        "revise/",
        DesignRevisionView.as_view(),
        name="email-design-revise",
    ),
]
