from django.urls import path

from .views import TestEmailSendView

urlpatterns = [
    path(
        "send-test/",
        TestEmailSendView.as_view(),
        name="email-delivery-send-test",
    ),
]
