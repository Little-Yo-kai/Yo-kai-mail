import logging

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ContentPlanRequestSerializer
from .services.gemini import (
    ContentPlanGenerationError,
    GeminiCampaignStrategist,
    GeminiGenerationNotConfiguredError,
)

logger = logging.getLogger(__name__)


class ContentPlanView(APIView):
    serializer_class = ContentPlanRequestSerializer

    @extend_schema(
        request=ContentPlanRequestSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Generate campaign content strategy",
        description=(
            "Combines BrandProfile, CampaignBrief, ReferenceDesignSpec, and "
            "available assets into a schema-validated ContentPlan."
        ),
    )
    def post(self, request):
        serializer = ContentPlanRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = GeminiCampaignStrategist().plan(
                brand_profile=serializer.validated_data["brand_profile"],
                campaign_brief=serializer.validated_data["campaign_brief"],
                reference_design_spec=serializer.validated_data[
                    "reference_design_spec"
                ],
                available_assets=serializer.validated_data.get(
                    "available_assets"
                ),
            )
        except GeminiGenerationNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ContentPlanGenerationError as exc:
            logger.exception("Campaign strategy generation failed")
            payload = {"success": False, "error": str(exc)}
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            detail_text = (exc.details or "").lower()
            response_status = status.HTTP_502_BAD_GATEWAY
            if (
                "rate limit" in detail_text
                or "too_many_requests" in detail_text
                or "error code: 429" in detail_text
            ):
                response_status = status.HTTP_429_TOO_MANY_REQUESTS
                payload["error"] = "Gemini generation rate limit exceeded."

            return Response(payload, status=response_status)

        return Response(
            {"success": True, "data": result},
            status=status.HTTP_200_OK,
        )
