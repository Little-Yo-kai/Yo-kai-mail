import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import WebsiteImportRequestSerializer
from .services.firecrawl import FirecrawlNotConfiguredError, FirecrawlService

logger = logging.getLogger(__name__)


class WebsiteImportView(APIView):
    @extend_schema(
        request=WebsiteImportRequestSerializer,
        summary="Import a website with Firecrawl",
        description=(
            "Checkpoint 1 endpoint. Scrapes one public URL with Firecrawl and "
            "returns the provider response. Normalization into WebsiteSnapshot "
            "is added in the next checkpoint."
        ),
    )
    def post(self, request):
        serializer = WebsiteImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            data = FirecrawlService().scrape(serializer.validated_data["url"])
        except FirecrawlNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Firecrawl website import failed")
            return Response(
                {"success": False, "error": "Firecrawl request failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {"success": True, "data": data},
            status=status.HTTP_200_OK,
        )
