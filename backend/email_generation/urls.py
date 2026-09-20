from django.urls import path

from .views import ContentPlanView

urlpatterns = [
    path("plan/", ContentPlanView.as_view(), name="email-content-plan"),
]
