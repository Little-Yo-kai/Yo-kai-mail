import logging

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import TestEmailSendSerializer
from .services.resend import (
    ResendDeliveryError,
    ResendEmailService,
    ResendNotConfiguredError,
)

logger = logging.getLogger(__name__)


class TestEmailSendView(APIView):
    serializer_class = TestEmailSendSerializer

    @extend_schema(
        request=TestEmailSendSerializer,
        summary="Send one rendered test email through Resend",
        description=(
            "Sends existing final HTML through Resend. This endpoint does not "
            "generate, rewrite, critique, or modify the email."
        ),
    )
    def post(self, request):
        serializer = TestEmailSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = ResendEmailService().send_test_email(
                to=serializer.validated_data["to"],
                subject=serializer.validated_data["subject"],
                html=serializer.validated_data["html"],
                idempotency_key=serializer.validated_data.get(
                    "idempotency_key"
                ),
            )
        except ResendNotConfiguredError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ResendDeliveryError as exc:
            logger.exception("Resend test delivery failed")

            payload = {
                "success": False,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            response_status = status.HTTP_502_BAD_GATEWAY
            if exc.status_code == 429:
                response_status = status.HTTP_429_TOO_MANY_REQUESTS
            elif exc.status_code in {400, 401, 403, 409, 422}:
                response_status = status.HTTP_400_BAD_REQUEST

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
