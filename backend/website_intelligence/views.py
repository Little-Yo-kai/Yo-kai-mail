import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .normalizers import build_website_snapshot
from .serializers import WebsiteImportRequestSerializer
from .services.firecrawl import FirecrawlNotConfiguredError, FirecrawlService

logger = logging.getLogger(__name__)


class WebsiteImportView(APIView):
    serializer_class = WebsiteImportRequestSerializer
    @extend_schema(
        request=WebsiteImportRequestSerializer,
        summary="Import and normalize a website",
        description=(
            "Scrapes one public URL with Firecrawl and normalizes the provider "
            "response into Yo-kai Mail's WebsiteSnapshot contract."
        ),
    )
    def post(self, request):
        serializer = WebsiteImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data["url"]

        try:
            raw_data = FirecrawlService().scrape(url)
            snapshot = build_website_snapshot(url, raw_data)
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
            {"success": True, "data": snapshot},
            status=status.HTTP_200_OK,
        )
