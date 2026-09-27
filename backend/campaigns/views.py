from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from demo_flow.service import DemoGenerationError

from .builders import build_campaign_brief
from .models import Campaign
from .serializers import (
    CampaignBriefSerializer,
    CampaignCreateSerializer,
    CampaignGenerateSerializer,
    CampaignSerializer,
    CampaignTransitionSerializer,
    CampaignUpdateSerializer,
)
from .services import (
    CampaignTransitionError,
    generate_campaign,
    transition_campaign,
)


def _owned_campaign(request, campaign_id):
    return get_object_or_404(
        Campaign.objects.select_related("active_design"),
        id=campaign_id,
        owner=request.user,
    )


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


class CampaignListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CampaignSerializer(many=True)},
        summary="List the current user's campaigns",
    )
    def get(self, request):
        campaigns = Campaign.objects.filter(
            owner=request.user
        ).select_related("active_design")

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaigns, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=CampaignCreateSerializer,
        responses={201: CampaignSerializer},
        summary="Create a persistent campaign draft",
    )
    def post(self, request):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        campaign = serializer.save(owner=request.user)

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CampaignDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CampaignSerializer},
        summary="Reopen a persistent campaign",
    )
    def get(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=CampaignUpdateSerializer,
        responses={200: CampaignSerializer},
        summary="Update editable campaign state",
    )
    def patch(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignUpdateSerializer(
            campaign,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignGenerateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=CampaignGenerateSerializer,
        responses={200: CampaignSerializer},
        summary="Generate and persist a campaign EmailDesign",
        description=(
            "Runs the current generation pipeline using the campaign's saved "
            "source URL and instructions, persists structured outputs, creates "
            "a new design version, and marks the campaign generated."
        ),
    )
    def post(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)

        serializer = CampaignGenerateSerializer(
            data=request.data,
            context={"campaign": campaign},
        )
        serializer.is_valid(raise_exception=True)

        try:
            campaign = generate_campaign(
                campaign,
                user=request.user,
                reference_image=serializer.validated_data.get(
                    "reference_image"
                ),
            )
        except CampaignTransitionError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except DemoGenerationError as exc:
            payload = {
                "success": False,
                "stage": exc.stage,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            return Response(
                payload,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        campaign.refresh_from_db()

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignTransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CampaignTransitionSerializer,
        responses={200: CampaignSerializer},
        summary="Move a campaign through an allowed lifecycle transition",
    )
    def post(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            campaign = transition_campaign(
                campaign,
                next_status=serializer.validated_data["status"],
            )
        except CampaignTransitionError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                    "current_status": campaign.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )
