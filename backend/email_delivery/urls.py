from django.urls import path

from .views import (
    CampaignDeliveryActivityView,
    CampaignScheduleCancelView,
    ContactDetailView,
    ContactImportView,
    ContactListDetailView,
    ContactListMembersView,
    ContactListView,
    ContactListsView,
    ResendWebhookView,
    TestEmailSendView,
    TestEmailStatusView,
)

urlpatterns = [
    path("campaigns/<uuid:campaign_id>/activity/", CampaignDeliveryActivityView.as_view(), name="campaign-delivery-activity"),
    path("campaigns/<uuid:campaign_id>/cancel-schedule/", CampaignScheduleCancelView.as_view(), name="campaign-schedule-cancel"),
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
    path("contacts/", ContactListView.as_view(), name="contact-list"),
    path(
        "contacts/import/",
        ContactImportView.as_view(),
        name="contact-import",
    ),
    path(
        "contacts/<uuid:contact_id>/",
        ContactDetailView.as_view(),
        name="contact-detail",
    ),
    path(
        "contact-lists/",
        ContactListsView.as_view(),
        name="contact-lists",
    ),
    path(
        "contact-lists/<uuid:list_id>/",
        ContactListDetailView.as_view(),
        name="contact-list-detail",
    ),
    path(
        "contact-lists/<uuid:list_id>/members/",
        ContactListMembersView.as_view(),
        name="contact-list-members",
    ),
    path("webhooks/resend/", ResendWebhookView.as_view(), name="resend-webhook"),
]
