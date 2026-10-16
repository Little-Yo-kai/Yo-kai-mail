from typing import ClassVar

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from email_assets.temp_cache import (
    EmailAssetCacheError,
    cache_image_bytes,
    read_cached_email_asset,
)
from email_rendering.compiler import MJMLCompilerError, compile_mjml_to_html
from email_rendering.renderer import EmailRenderInputError, render_email_to_mjml
from email_rendering.serializers import MJMLRenderRequestSerializer

from .preview import build_preview_html


class DemoImageSerializer(serializers.Serializer):
    image = serializers.FileField()

    def validate_image(self, value):
        if value.size > settings.EMAIL_ASSET_MAX_IMAGE_BYTES:
            raise serializers.ValidationError("Image exceeds the 8 MB upload limit.")
        return value


class DemoImageUploadView(APIView):
    serializer_class = DemoImageSerializer
    parser_classes: ClassVar = [MultiPartParser, FormParser]

    @extend_schema(
        responses=OpenApiTypes.OBJECT, summary="Upload a replacement email image"
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            cached = cache_image_bytes(
                serializer.validated_data["image"].read(),
                source_url=request.build_absolute_uri("/api/demo/assets/")
                + "{cache_key}/",
            )
        except EmailAssetCacheError as exc:
            return Response({"success": False, "error": str(exc)}, status=400)
        return Response(
            {
                "success": True,
                "data": {
                    "asset": {
                        "asset_id": f"upload_{cached.cache_key[:16]}",
                        "kind": "product",
                        "source": "request",
                        "url": cached.source_url,
                    },
                    "cached_asset": cached.public_manifest(),
                },
            }
        )


class DemoImageView(APIView):
    authentication_classes: ClassVar = []

    @extend_schema(
        responses={200: OpenApiTypes.BINARY}, summary="Read a temporary email image"
    )
    def get(self, request, cache_key):
        try:
            cached = read_cached_email_asset(cache_key)
        except EmailAssetCacheError:
            return Response({"error": "Image expired or unavailable."}, status=404)
        response = HttpResponse(cached.body, content_type=cached.mime_type)
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response


class DemoRenderView(APIView):
    serializer_class = MJMLRenderRequestSerializer

    @extend_schema(
        responses=OpenApiTypes.OBJECT,
        summary="Apply copy, image and layout edits without an AI call",
    )
    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            rendered = render_email_to_mjml(**data)
            compiled = compile_mjml_to_html(rendered["mjml"])
            preview, diagnostics, cached = build_preview_html(
                html_document=compiled["html"],
                asset_inventory=data["asset_inventory"],
            )
        except (EmailRenderInputError, MJMLCompilerError) as exc:
            return Response({"success": False, "error": str(exc)}, status=400)
        return Response(
            {
                "success": True,
                "data": {
                    "html": compiled["html"],
                    "text": compiled.get("text", ""),
                    "warnings": rendered.get("warnings", []),
                    "preview_html": preview,
                    "mjml": rendered["mjml"],
                    "compiler_errors": compiled["compiler_errors"],
                    "rendered_sections": rendered["rendered_sections"],
                    "resolved_theme": rendered["resolved_theme"],
                    "preview_asset_diagnostics": diagnostics,
                    "cached_assets": cached,
                    "delivery_ready": all(
                        item["status"] == "embedded" for item in diagnostics
                    ),
                },
            }
        )
