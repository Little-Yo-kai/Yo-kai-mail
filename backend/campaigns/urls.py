from django.urls import path

from .views import (
    CampaignBriefView,
    CampaignCancelScheduleView,
    CampaignDesignView,
    CampaignAudienceResolveView,
    CampaignDetailView,
    CampaignDeliverySummaryView,
    CampaignGenerateView,
    CampaignListCreateView,
    CampaignRenderView,
    CampaignScheduleView,
    CampaignSendView,
    CampaignTestSendView,
    CampaignTransitionView,
)

urlpatterns = [
    path("", CampaignListCreateView.as_view(), name="campaign-list-create"),
    path("brief/", CampaignBriefView.as_view(), name="campaign-brief"),
    path(
        "<uuid:campaign_id>/",
        CampaignDetailView.as_view(),
        name="campaign-detail",
    ),
    path(
        "<uuid:campaign_id>/generate/",
        CampaignGenerateView.as_view(),
        name="campaign-generate",
    ),
    path(
        "<uuid:campaign_id>/design/",
        CampaignDesignView.as_view(),
        name="campaign-design",
    ),
    path(
        "<uuid:campaign_id>/render/",
        CampaignRenderView.as_view(),
        name="campaign-render",
    ),
    path(
        "<uuid:campaign_id>/send-test/",
        CampaignTestSendView.as_view(),
        name="campaign-send-test",
    ),
    path(
        "<uuid:campaign_id>/audience/resolve/",
        CampaignAudienceResolveView.as_view(),
        name="campaign-audience-resolve",
    ),
    path(
        "<uuid:campaign_id>/send/",
        CampaignSendView.as_view(),
        name="campaign-send",
    ),
    path(
        "<uuid:campaign_id>/schedule/",
        CampaignScheduleView.as_view(),
        name="campaign-schedule",
    ),
    path(
        "<uuid:campaign_id>/cancel-schedule/",
        CampaignCancelScheduleView.as_view(),
        name="campaign-cancel-schedule",
    ),
    path(
        "<uuid:campaign_id>/delivery-summary/",
        CampaignDeliverySummaryView.as_view(),
        name="campaign-delivery-summary",
    ),
    path(
        "<uuid:campaign_id>/transition/",
        CampaignTransitionView.as_view(),
        name="campaign-transition",
    ),
]
