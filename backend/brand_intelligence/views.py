import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import BrandAnalysisRequestSerializer
from .services.gemini import (
    BrandAnalysisError,
    GeminiBrandService,
    GeminiNotConfiguredError,
)

logger = logging.getLogger(__name__)


class BrandAnalyzeView(APIView):
    @extend_schema(
        request=BrandAnalysisRequestSerializer,
        summary="Analyze a WebsiteSnapshot with Gemini",
        description=(
            "Converts WebsiteSnapshot evidence into a validated BrandProfile "
            "using Gemini structured output."
        ),
    )
    def post(self, request):
        serializer = BrandAnalysisRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            profile = GeminiBrandService().analyze(
                serializer.validated_data["snapshot"]
            )
        except GeminiNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except BrandAnalysisError as exc:
            logger.exception("Gemini brand analysis failed")
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"success": True, "data": profile},
            status=status.HTTP_200_OK,
        )
