import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .normalizers import build_website_snapshot
from .serializers import (
    WebsiteImportRequestSerializer,
   
)
from .services.firecrawl import FirecrawlNotConfiguredError, FirecrawlService
from .services.crawl_import import build_website_crawl_snapshot

logger = logging.getLogger(__name__)


class WebsiteImportView(APIView):
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


class WebsiteCrawlImportView(APIView):

    @extend_schema(
        request=WebsiteImportRequestSerializer,
        summary="Crawl, normalize, and save multiple pages of a website",
        description=(
            "Crawls up to `limit` pages of one site with Firecrawl, respecting "
            "robots.txt and skipping irrelevant paths (login/cart/etc.), "
            "normalizes each into a WebsiteSnapshot"
        ),
    )
    def post(self, request):
        serializer = WebsiteImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        url = serializer.validated_data["url"]
        limit = serializer.validated_data["limit"]

        try:
            result = build_website_crawl_snapshot(url, limit=limit)
        except FirecrawlNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Exception:
            logger.exception("Firecrawl website crawl import failed")
            return Response(
                {"success": False, "error": "Firecrawl request failed."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not result["robots_allowed"]:
            return Response(
                {
                    "success": False,
                    "error": "robots.txt disallows crawling this site.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(
            {
                "success": True,
                "data": result,
            },
            status=status.HTTP_200_OK,
        )