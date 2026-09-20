import logging

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from email_rendering.compiler import (
    MJMLCompilerError,
    compile_mjml_to_html,
)
from email_rendering.renderer import (
    EmailRenderInputError,
    render_email_to_mjml,
)
from email_rendering.screenshot import (
    EmailScreenshotError,
    capture_email_screenshot,
)

from .serializers import DesignCritiqueRequestSerializer
from .services.gemini import (
    DesignCriticNotConfiguredError,
    DesignCritiqueError,
    GeminiDesignCritic,
)

logger = logging.getLogger(__name__)


class DesignCritiqueView(APIView):
    serializer_class = DesignCritiqueRequestSerializer

    @extend_schema(
        request=DesignCritiqueRequestSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Critique a rendered email visually",
        description=(
            "Renders EmailDesign to responsive HTML, captures the result in "
            "headless Chromium, and asks the multimodal design critic for a "
            "schema-validated visual critique. The screenshot stays internal."
        ),
    )
    def post(self, request):
        serializer = DesignCritiqueRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        asset_inventory = serializer.validated_data.get(
            "asset_inventory",
            [],
        )

        try:
            render_result = render_email_to_mjml(
                brand_profile=serializer.validated_data["brand_profile"],
                email_design=serializer.validated_data["email_design"],
                asset_inventory=asset_inventory,
            )
            compile_result = compile_mjml_to_html(
                render_result["mjml"]
            )
            screenshot_result = capture_email_screenshot(
                compile_result["html"],
                asset_urls=[
                    item.get("url")
                    for item in asset_inventory
                    if isinstance(item, dict) and item.get("url")
                ],
            )

            critique = GeminiDesignCritic().critique(
                screenshot_base64=screenshot_result["image_base64"],
                screenshot_mime_type=screenshot_result["mime_type"],
                brand_profile=serializer.validated_data["brand_profile"],
                email_design=serializer.validated_data["email_design"],
                reference_design_spec=serializer.validated_data[
                    "reference_design_spec"
                ],
                asset_inventory=asset_inventory,
                render_metadata={
                    "width": screenshot_result["width"],
                    "height": screenshot_result["height"],
                    "rendered_sections": render_result[
                        "rendered_sections"
                    ],
                    "available_asset_ids": render_result[
                        "available_asset_ids"
                    ],
                    "image_diagnostics": screenshot_result[
                        "image_diagnostics"
                    ],
                },
            )
        except EmailRenderInputError as exc:
            return Response(
                {
                    "success": False,
                    "error": "Invalid email rendering input.",
                    "details": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except MJMLCompilerError as exc:
            payload = {
                "success": False,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details
            return Response(
                payload,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except EmailScreenshotError as exc:
            payload = {
                "success": False,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details
            return Response(
                payload,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except DesignCriticNotConfiguredError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except DesignCritiqueError as exc:
            logger.exception("Visual email critique failed")
            payload = {
                "success": False,
                "error": str(exc),
            }
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
                payload["error"] = (
                    "Gemini design critic rate limit exceeded."
                )

            return Response(
                payload,
                status=response_status,
            )

        return Response(
            {
                "success": True,
                "data": {
                    "design_critique": critique,
                    "render_metadata": {
                        "width": screenshot_result["width"],
                        "height": screenshot_result["height"],
                        "mime_type": screenshot_result["mime_type"],
                        "image_diagnostics": screenshot_result[
                            "image_diagnostics"
                        ],
                    },
                    "compiler_errors": compile_result[
                        "compiler_errors"
                    ],
                },
            },
            status=status.HTTP_200_OK,
        )
