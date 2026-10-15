import json
import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import (
    Contact,
    ContactList,
    ContactListMembership,
)
from .serializers import (
    TestEmailSendSerializer,
    TestEmailStatusResponseSerializer,
)
from .serializers_campaign import (
    ContactImportSerializer,
    ContactListMembersSerializer,
    ContactListSerializer,
    ContactSerializer,
    ContactUpdateSerializer,
    DeliveryActivityQuerySerializer,
    DeliveryActivityResponseSerializer,
    ResendWebhookResponseSerializer,
)
from .services.campaigns import (
    CampaignDeliveryError,
    ContactImportError,
    cancel_campaign_schedule,
    get_campaign_delivery_activity,
    import_contacts_csv,
    record_resend_webhook,
    verify_resend_signature,
)
from .services.resend import (
    ResendDeliveryError,
    ResendEmailService,
    ResendNotConfiguredError,
)

logger = logging.getLogger(__name__)


class CampaignDeliveryActivityView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeliveryActivityResponseSerializer

    @extend_schema(
        parameters=[DeliveryActivityQuerySerializer],
        responses={200: DeliveryActivityResponseSerializer},
        summary="Read owner-scoped campaign job and recipient activity",
    )
    def get(self, request, campaign_id):
        from campaigns.models import Campaign

        campaign = get_object_or_404(Campaign, pk=campaign_id, owner=request.user)
        query = DeliveryActivityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response({"success": True, "data": get_campaign_delivery_activity(
            campaign=campaign, **query.validated_data,
        )})


class CampaignScheduleCancelView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = DeliveryActivityResponseSerializer

    @extend_schema(request=None, summary="Cancel a scheduled campaign before delivery starts")
    def post(self, request, campaign_id):
        from campaigns.models import Campaign

        get_object_or_404(Campaign, pk=campaign_id, owner=request.user)
        try:
            job = cancel_campaign_schedule(campaign_id=campaign_id, owner=request.user)
        except CampaignDeliveryError as exc:
            return Response({"success": False, "error": str(exc)}, status=409)
        return Response({"success": True, "data": {"job_id": str(job.id), "status": job.status}})


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
        if not settings.RESEND_TEST_SEND_ENABLED:
            return Response(
                {
                    "success": False,
                    "error": "Test email sending is disabled.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TestEmailSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = ResendEmailService().send_test_email(
                to=serializer.validated_data["to"],
                subject=serializer.validated_data["subject"],
                html=serializer.validated_data["html"],
                cached_assets=serializer.validated_data.get(
                    "cached_assets",
                    [],
                ),
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



class TestEmailStatusView(APIView):
    serializer_class = TestEmailStatusResponseSerializer

    @extend_schema(
        request=None,
        responses={200: TestEmailStatusResponseSerializer},
        summary="Get Resend status for a test email",
        description=(
            "Retrieves the latest provider event for one previously sent "
            "test email."
        ),
    )
    def get(self, request, email_id: str):
        if not settings.RESEND_TEST_SEND_ENABLED:
            return Response(
                {
                    "success": False,
                    "error": "Test email sending is disabled.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = ResendEmailService().get_email_status(
                email_id=email_id
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
            logger.exception("Resend status lookup failed")

            payload = {
                "success": False,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            response_status = status.HTTP_502_BAD_GATEWAY
            if exc.status_code == 429:
                response_status = status.HTTP_429_TOO_MANY_REQUESTS
            elif exc.status_code in {400, 401, 403, 404, 422}:
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


class ContactListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: ContactSerializer(many=True)})
    def get(self, request):
        contacts = Contact.objects.filter(owner=request.user)
        list_id = request.query_params.get("list_id")
        if list_id:
            contact_list = get_object_or_404(
                ContactList,
                owner=request.user,
                id=list_id,
            )
            contacts = contacts.filter(
                list_memberships__contact_list=contact_list
            )
        status_filter = request.query_params.get("status")
        if status_filter:
            contacts = contacts.filter(status=status_filter)
        return Response(
            {"success": True, "data": ContactSerializer(contacts.distinct(), many=True).data},
            status=status.HTTP_200_OK,
        )


class ContactDetailView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactUpdateSerializer

    def patch(self, request, contact_id):
        contact = get_object_or_404(
            Contact,
            owner=request.user,
            id=contact_id,
        )
        serializer = ContactUpdateSerializer(
            contact,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        contact = serializer.save()
        return Response(
            {"success": True, "data": ContactSerializer(contact).data},
            status=status.HTTP_200_OK,
        )


class ContactImportView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ContactImportSerializer

    @extend_schema(
        request=ContactImportSerializer,
        summary="Import contacts from a CSV file",
        description=(
            "Required column: email. Optional columns include first_name, "
            "last_name, display_name, consent_status, consented_at, "
            "consent_source, and source. A contact is eligible for a campaign "
            "only after active consent has been recorded."
        ),
    )
    def post(self, request):
        serializer = ContactImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_list = None
        list_id = serializer.validated_data.get("list_id")
        if list_id:
            contact_list = get_object_or_404(
                ContactList,
                owner=request.user,
                id=list_id,
            )
        try:
            summary = import_contacts_csv(
                uploaded_file=serializer.validated_data["file"],
                owner=request.user,
                contact_list=contact_list,
            )
        except ContactImportError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"success": True, "data": summary},
            status=status.HTTP_200_OK,
        )


class ContactListsView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactListSerializer

    @extend_schema(responses={200: ContactListSerializer(many=True)}, operation_id="email_delivery_contact_lists_list")
    def get(self, request):
        lists = ContactList.objects.filter(owner=request.user)
        return Response(
            {"success": True, "data": ContactListSerializer(lists, many=True).data},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = ContactListSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                contact_list = serializer.save(owner=request.user)
        except IntegrityError:
            return Response(
                {"success": False, "error": "A contact list with that name already exists."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"success": True, "data": ContactListSerializer(contact_list).data},
            status=status.HTTP_201_CREATED,
        )


class ContactListDetailView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactListSerializer

    def get(self, request, list_id):
        contact_list = get_object_or_404(
            ContactList,
            id=list_id,
            owner=request.user,
        )
        return Response(
            {"success": True, "data": ContactListSerializer(contact_list).data},
            status=status.HTTP_200_OK,
        )

    def patch(self, request, list_id):
        contact_list = get_object_or_404(
            ContactList,
            id=list_id,
            owner=request.user,
        )
        serializer = ContactListSerializer(
            contact_list,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                contact_list = serializer.save()
        except IntegrityError:
            return Response(
                {"success": False, "error": "A contact list with that name already exists."},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"success": True, "data": ContactListSerializer(contact_list).data},
            status=status.HTTP_200_OK,
        )


class ContactListMembersView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ContactListMembersSerializer

    def get(self, request, list_id):
        contact_list = get_object_or_404(
            ContactList,
            id=list_id,
            owner=request.user,
        )
        contacts = Contact.objects.filter(
            owner=request.user,
            list_memberships__contact_list=contact_list,
        ).distinct()
        return Response(
            {"success": True, "data": ContactSerializer(contacts, many=True).data},
            status=status.HTTP_200_OK,
        )

    @extend_schema(request=ContactListMembersSerializer)
    def post(self, request, list_id):
        contact_list = get_object_or_404(
            ContactList,
            id=list_id,
            owner=request.user,
        )
        serializer = ContactListMembersSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact_ids = set(serializer.validated_data["contact_ids"])
        contacts = list(
            Contact.objects.filter(owner=request.user, id__in=contact_ids)
        )
        if len(contacts) != len(contact_ids):
            return Response(
                {"success": False, "error": "One or more contacts were not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        added = 0
        with transaction.atomic():
            for contact in contacts:
                _, created = ContactListMembership.objects.get_or_create(
                    contact_list=contact_list,
                    contact=contact,
                    defaults={"source": "manual"},
                )
                added += int(created)
        return Response(
            {"success": True, "data": {"added": added, "member_count": contact_list.memberships.count()}},
            status=status.HTTP_200_OK,
        )


class ResendWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    serializer_class = ResendWebhookResponseSerializer

    @extend_schema(
        request=None,
        summary="Ingest a signed Resend delivery event",
        description=(
            "Validates Resend's Svix signature against the raw request body, "
            "then idempotently records supported email events."
        ),
    )
    def post(self, request):
        if not settings.RESEND_WEBHOOK_SECRET:
            return Response(
                {"success": False, "error": "Resend webhook verification is not configured."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        raw_body = request.body
        if not verify_resend_signature(
            raw_body=raw_body,
            headers=request.headers,
            secret=settings.RESEND_WEBHOOK_SECRET,
        ):
            return Response(
                {"success": False, "error": "Invalid webhook signature."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            payload = json.loads(raw_body)
            if not isinstance(payload, dict):
                raise ValueError("Invalid Resend webhook payload.")
            result = record_resend_webhook(
                provider_event_id=request.headers.get("svix-id"),
                payload=payload,
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {"success": True, "data": result},
            status=status.HTTP_200_OK,
        )
