from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .compiler import MJMLCompilerError, compile_mjml_to_html
from .renderer import EmailRenderInputError, render_email_to_mjml
from .serializers import MJMLRenderRequestSerializer


class MJMLRenderView(APIView):
    serializer_class = MJMLRenderRequestSerializer

    @extend_schema(
        request=MJMLRenderRequestSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Render EmailDesign to deterministic MJML",
        description=(
            "Validates BrandProfile, EmailDesign, and AssetInventory, resolves "
            "semantic theme roles, and produces deterministic MJML. No AI call "
            "is made by this endpoint."
        ),
    )
    def post(self, request):
        serializer = MJMLRenderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = render_email_to_mjml(
                brand_profile=serializer.validated_data["brand_profile"],
                email_design=serializer.validated_data["email_design"],
                asset_inventory=serializer.validated_data.get(
                    "asset_inventory",
                    [],
                ),
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

        return Response(
            {"success": True, "data": result},
            status=status.HTTP_200_OK,
        )



class HTMLRenderView(APIView):
    serializer_class = MJMLRenderRequestSerializer

    @extend_schema(
        request=MJMLRenderRequestSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Render EmailDesign to responsive HTML",
        description=(
            "Runs the deterministic EmailDesign-to-MJML renderer and compiles "
            "the result with the local official MJML runtime. No AI call is "
            "made by this endpoint."
        ),
    )
    def post(self, request):
        serializer = MJMLRenderRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            render_result = render_email_to_mjml(
                brand_profile=serializer.validated_data["brand_profile"],
                email_design=serializer.validated_data["email_design"],
                asset_inventory=serializer.validated_data.get(
                    "asset_inventory",
                    [],
                ),
            )
            compile_result = compile_mjml_to_html(render_result["mjml"])
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
            if exc.details:
                payload["details"] = exc.details

            return Response(
                payload,
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "success": True,
                "data": {
                    "html": compile_result["html"],
                    "compiler_errors": compile_result["compiler_errors"],
                    "mjml": render_result["mjml"],
                    "resolved_theme": render_result["resolved_theme"],
                    "rendered_sections": render_result["rendered_sections"],
                    "available_asset_ids": render_result[
                        "available_asset_ids"
                    ],
                },
            },
            status=status.HTTP_200_OK,
        )
