from django.urls import path

from .views import TestEmailSendView, TestEmailStatusView

urlpatterns = [
    path(
        "send-test/",
        TestEmailSendView.as_view(),
        name="email-delivery-send-test",
    ),
    path(
        "status/<str:email_id>/",
        TestEmailStatusView.as_view(),
        name="email-delivery-status",
    ),
]
