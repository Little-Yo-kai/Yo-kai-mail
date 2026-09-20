import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ReferenceDesignAnalyzeSerializer
from .services.gemini import (
    GeminiNotConfiguredError,
    GeminiReferenceDesignService,
    ReferenceDesignAnalysisError,
)

logger = logging.getLogger(__name__)


class ReferenceDesignAnalyzeView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=ReferenceDesignAnalyzeSerializer,
        summary="Analyze a reference marketing email image",
        description=(
            "Uses Gemini vision to reverse-engineer reusable email composition "
            "into Yo-kai Mail's ReferenceDesignSpec contract."
        ),
    )
    def post(self, request):
        serializer = ReferenceDesignAnalyzeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            spec = GeminiReferenceDesignService().analyze(
                serializer.validated_data["image"]
            )
        except GeminiNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ReferenceDesignAnalysisError as exc:
            logger.exception("Reference design analysis failed")
            payload = {"success": False, "error": str(exc)}
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            return Response(
                payload,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"success": True, "data": spec},
            status=status.HTTP_200_OK,
        )
