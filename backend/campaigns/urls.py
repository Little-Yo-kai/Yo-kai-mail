from django.urls import path

from .views import CampaignBriefView

urlpatterns = [
    path("brief/", CampaignBriefView.as_view(), name="campaign-brief"),
]
