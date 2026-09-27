from django.urls import path

from .views import (
    CampaignBriefView,
    CampaignDetailView,
    CampaignGenerateView,
    CampaignListCreateView,
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
        "<uuid:campaign_id>/transition/",
        CampaignTransitionView.as_view(),
        name="campaign-transition",
    ),
]
