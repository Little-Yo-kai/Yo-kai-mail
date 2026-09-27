from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .builders import build_campaign_brief
from .serializers import CampaignBriefSerializer


class CampaignBriefView(APIView):
    serializer_class = CampaignBriefSerializer
    @extend_schema(
        request=CampaignBriefSerializer,
        summary="Validate and normalize a campaign brief",
        description=(
            "Accepts user campaign intent and returns Yo-kai Mail's stable "
            "CampaignBrief contract for downstream generation."
        ),
    )
    def post(self, request):
        serializer = CampaignBriefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        brief = build_campaign_brief(serializer.validated_data)

        return Response(
            {"success": True, "data": brief},
            status=status.HTTP_200_OK,
        )
