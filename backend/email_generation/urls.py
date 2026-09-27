from django.urls import path

from .views import ContentPlanView, EmailDesignView

urlpatterns = [
    path("plan/", ContentPlanView.as_view(), name="email-content-plan"),
    path("design/", EmailDesignView.as_view(), name="email-design"),
]
