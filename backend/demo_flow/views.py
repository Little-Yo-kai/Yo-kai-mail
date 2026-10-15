import logging
from typing import ClassVar

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.provider_errors import is_provider_rate_limited

from .serializers import DemoGenerateSerializer
from .service import DemoGenerationError, generate_phase1_demo

logger = logging.getLogger(__name__)


class DemoGenerateView(APIView):
    serializer_class = DemoGenerateSerializer
    parser_classes: ClassVar = [MultiPartParser, FormParser]

    @extend_schema(
        request=DemoGenerateSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Generate a complete Phase 1 demo email",
        description=(
            "Runs website import, brand analysis, automatic or uploaded "
            "reference selection, campaign strategy, structured email design, "
            "MJML rendering, and responsive HTML compilation in one request. "
            "Visual critique, revision loops, and asset validation are "
            "intentionally not part of this temporary demo path."
        ),
    )
    def post(self, request):
        serializer = DemoGenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = generate_phase1_demo(
                url=serializer.validated_data["url"],
                reference_image=serializer.validated_data.get(
                    "reference_image"
                ),
                additional_instructions=serializer.validated_data.get(
                    "additional_instructions",
                    "",
                ),
            )
        except DemoGenerationError as exc:
            logger.exception(
                "Phase 1 demo generation failed at %s",
                exc.stage,
            )
            payload = {
                "success": False,
                "stage": exc.stage,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            response_status = status.HTTP_502_BAD_GATEWAY
            if is_provider_rate_limited(exc, details=exc.details):
                response_status = status.HTTP_429_TOO_MANY_REQUESTS

            return Response(
                payload,
                status=response_status,
            )

        return Response(
            {
                "success": True,
                "data": result,
            },
            status=status.HTTP_200_OK,
        )
