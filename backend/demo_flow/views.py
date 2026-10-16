from typing import ClassVar

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import StreamingHttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .runner import GenerationBusy, GenerationRun
from .serializers import DemoGenerateSerializer
from .service import generate_phase1_demo


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

        image = serializer.validated_data.get("reference_image")
        # The request's temporary upload may close when a streaming response
        # disconnects. Give the bounded worker its own copy (max 15 MB).
        if image is not None:
            image = SimpleUploadedFile(
                image.name, image.read(), content_type=image.content_type
            )

        try:
            run = GenerationRun(
                generate_phase1_demo,
                url=serializer.validated_data["url"],
                reference_image=image,
                additional_instructions=serializer.validated_data.get(
                    "additional_instructions",
                    "",
                ),
            )
        except GenerationBusy as exc:
            if image is not None:
                image.close()
            return Response(
                {"success": False, "code": "server_busy", "error": str(exc)},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        if self.stream:
            stream = run.async_stream() if hasattr(request._request, "scope") else run
            response = StreamingHttpResponse(
                stream, content_type="application/x-ndjson"
            )
            response["Cache-Control"] = "no-cache, no-transform"
            response["X-Accel-Buffering"] = "no"
            return response

        for event in run.events():
            if event["type"] in {"result", "error"}:
                payload = {
                    key: value
                    for key, value in event.items()
                    if key not in {"type", "status"}
                }
                return Response(payload, status=event.get("status", status.HTTP_200_OK))

    stream = False


class DemoGenerateStreamView(DemoGenerateView):
    stream = True

    @extend_schema(
        request=DemoGenerateSerializer,
        responses=OpenApiTypes.OBJECT,
        summary="Generate an email with live stage progress",
        description=(
            "Newline-delimited JSON: started (request ID and deadline), progress, "
            "heartbeat, then exactly one result or error. Inspect the final event's "
            "success/status fields; HTTP headers have already been sent. The same "
            "validated pipeline and time budget are used by the JSON endpoint."
        ),
    )
    def post(self, request):
        return super().post(request)
