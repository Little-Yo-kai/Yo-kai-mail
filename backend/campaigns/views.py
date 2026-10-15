from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from demo_flow.service import DemoGenerationError
from email_delivery.services.resend import (
    ResendDeliveryError,
    ResendNotConfiguredError,
)
from email_rendering.compiler import MJMLCompilerError
from email_rendering.renderer import EmailRenderInputError

from .builders import build_campaign_brief
from .models import Campaign, CampaignStatus
from .serializers import (
    CampaignBriefSerializer,
    CampaignCreateSerializer,
    CampaignDesignSaveSerializer,
    CampaignGenerateSerializer,
    CampaignRenderResponseSerializer,
    CampaignSerializer,
    CampaignTestSendSerializer,
    CampaignTransitionSerializer,
    CampaignUpdateSerializer,
)
from email_delivery.models import (
    DeliveryEvent,
    DeliveryRecord,
    DeliveryRecordStatus,
)
from email_delivery.serializers_campaign import (
    ResolveAudienceSerializer,
    ScheduleCampaignSerializer,
)
from email_delivery.services.campaigns import (
    CampaignDeliveryError,
    CampaignQueueError,
    cancel_campaign_schedule,
    create_campaign_send_job,
    dispatch_campaign_send_job,
    resolve_campaign_audience,
)
from .services import (
    CampaignTransitionError,
    CampaignWorkflowError,
    generate_campaign,
    render_campaign_email,
    save_campaign_design,
    send_campaign_test,
    transition_campaign,
)


def _owned_campaign(request, campaign_id):
    return get_object_or_404(
        Campaign.objects.select_related("active_design"),
        id=campaign_id,
        owner=request.user,
    )


class CampaignBriefView(APIView):
    serializer_class = CampaignBriefSerializer

    @extend_schema(
        request=CampaignBriefSerializer,
        summary="Validate and normalize a campaign brief",
        description=(
            "Accepts user campaign intent and returns Yo-kai Mail's stable "
            "CampaignBrief contract for downstream generation."
        ),
    )
    def post(self, request):
        serializer = CampaignBriefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        brief = build_campaign_brief(serializer.validated_data)

        return Response(
            {"success": True, "data": brief},
            status=status.HTTP_200_OK,
        )


class CampaignListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CampaignSerializer(many=True)},
        summary="List the current user's campaigns",
    )
    def get(self, request):
        campaigns = Campaign.objects.filter(
            owner=request.user
        ).select_related("active_design")

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaigns, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=CampaignCreateSerializer,
        responses={201: CampaignSerializer},
        summary="Create a persistent campaign draft",
    )
    def post(self, request):
        serializer = CampaignCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        campaign = serializer.save(owner=request.user)

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CampaignDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: CampaignSerializer},
        summary="Reopen a persistent campaign",
    )
    def get(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=CampaignUpdateSerializer,
        responses={200: CampaignSerializer},
        summary="Update editable campaign state",
    )
    def patch(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignUpdateSerializer(
            campaign,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        campaign = serializer.save()

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignGenerateView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        request=CampaignGenerateSerializer,
        responses={200: CampaignSerializer},
        summary="Generate and persist a campaign EmailDesign",
        description=(
            "Runs the current generation pipeline using the campaign's saved "
            "source URL and instructions, persists structured outputs, creates "
            "a new design version, and marks the campaign generated."
        ),
    )
    def post(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)

        serializer = CampaignGenerateSerializer(
            data=request.data,
            context={"campaign": campaign},
        )
        serializer.is_valid(raise_exception=True)

        try:
            campaign = generate_campaign(
                campaign,
                user=request.user,
                reference_image=serializer.validated_data.get(
                    "reference_image"
                ),
            )
        except CampaignTransitionError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except DemoGenerationError as exc:
            payload = {
                "success": False,
                "stage": exc.stage,
                "error": str(exc),
            }
            if settings.DEBUG and exc.details:
                payload["details"] = exc.details

            return Response(
                payload,
                status=status.HTTP_502_BAD_GATEWAY,
            )

        campaign.refresh_from_db()

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignTransitionView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=CampaignTransitionSerializer,
        responses={200: CampaignSerializer},
        summary="Move a campaign through an allowed lifecycle transition",
    )
    def post(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested_status = serializer.validated_data["status"]
        if requested_status not in {
            CampaignStatus.REVIEWED,
            CampaignStatus.READY,
        }:
            return Response(
                {
                    "success": False,
                    "error": (
                        "This status is managed by generation, test delivery, "
                        "or the campaign delivery workflow."
                    ),
                },
                status=status.HTTP_409_CONFLICT,
            )
        if (
            campaign.status == CampaignStatus.SCHEDULED
            and requested_status == CampaignStatus.READY
        ):
            return Response(
                {
                    "success": False,
                    "error": "Cancel the scheduled delivery before returning to ready.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        try:
            campaign = transition_campaign(
                campaign,
                next_status=requested_status,
            )
        except CampaignTransitionError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                    "current_status": campaign.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignAudienceResolveView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ResolveAudienceSerializer

    @extend_schema(
        request=ResolveAudienceSerializer,
        summary="Resolve and save a suppression-aware campaign audience",
        description=(
            "Accepts owned contact/list IDs, deduplicates recipients, excludes "
            "inactive or unconsented contacts, and stores an immutable snapshot."
        ),
    )
    def post(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = ResolveAudienceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = resolve_campaign_audience(
                campaign_id=campaign.id,
                owner=request.user,
                list_ids=serializer.validated_data["list_ids"],
                contact_ids=serializer.validated_data["contact_ids"],
            )
        except CampaignDeliveryError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {"success": True, "data": result},
            status=status.HTTP_200_OK,
        )


class CampaignSendView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Queue a ready campaign for immediate delivery")
    def post(self, request, campaign_id):
        if not settings.RESEND_CAMPAIGN_SEND_ENABLED:
            return Response(
                {"success": False, "error": "Campaign sending is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )
        _owned_campaign(request, campaign_id)
        try:
            job = create_campaign_send_job(
                campaign_id=campaign_id,
                owner=request.user,
            )
            dispatch_campaign_send_job(job)
            job.refresh_from_db()
        except CampaignDeliveryError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except CampaignWorkflowError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except CampaignQueueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Campaign.DoesNotExist:
            return Response(
                {"success": False, "error": "Campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "success": True,
                "data": {
                    "job_id": str(job.id),
                    "status": job.status,
                    "campaign_id": str(campaign_id),
                    "recipient_count": job.deliveries.count(),
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CampaignScheduleView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ScheduleCampaignSerializer

    @extend_schema(
        request=ScheduleCampaignSerializer,
        summary="Schedule a ready campaign for delivery",
    )
    def post(self, request, campaign_id):
        if not settings.RESEND_CAMPAIGN_SEND_ENABLED:
            return Response(
                {"success": False, "error": "Campaign sending is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )
        _owned_campaign(request, campaign_id)
        serializer = ScheduleCampaignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            job = create_campaign_send_job(
                campaign_id=campaign_id,
                owner=request.user,
                scheduled_for=serializer.validated_data["scheduled_for"],
            )
            dispatch_campaign_send_job(job)
            job.refresh_from_db()
        except CampaignDeliveryError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except CampaignWorkflowError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except CampaignQueueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except Campaign.DoesNotExist:
            return Response(
                {"success": False, "error": "Campaign not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                "success": True,
                "data": {
                    "job_id": str(job.id),
                    "status": job.status,
                    "scheduled_for": job.scheduled_for,
                    "campaign_id": str(campaign_id),
                    "recipient_count": job.deliveries.count(),
                },
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CampaignCancelScheduleView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Cancel a scheduled campaign before delivery starts")
    def post(self, request, campaign_id):
        _owned_campaign(request, campaign_id)
        try:
            job = cancel_campaign_schedule(
                campaign_id=campaign_id,
                owner=request.user,
            )
        except CampaignDeliveryError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            {
                "success": True,
                "data": {
                    "job_id": str(job.id),
                    "status": job.status,
                    "campaign_id": str(campaign_id),
                },
            },
            status=status.HTTP_200_OK,
        )


class CampaignDeliverySummaryView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get campaign delivery counts and job status")
    def get(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        records = DeliveryRecord.objects.filter(campaign=campaign)
        try:
            limit = int(request.query_params.get("limit", "100"))
            offset = int(request.query_params.get("offset", "0"))
        except ValueError:
            return Response(
                {"success": False, "error": "limit and offset must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if limit < 1 or limit > 500 or offset < 0:
            return Response(
                {"success": False, "error": "Use a limit from 1 to 500 and a non-negative offset."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        recipient_count = records.count()
        recipient_records = list(
            records.order_by("created_at", "id")
            .values(
                "id",
                "recipient_email",
                "provider",
                "provider_message_id",
                "status",
                "last_event_type",
                "last_event_at",
                "sent_at",
                "failure_reason",
            )[offset : offset + limit]
        )
        sent_states = {
            DeliveryRecordStatus.SENT,
            DeliveryRecordStatus.DELIVERY_DELAYED,
            DeliveryRecordStatus.DELIVERED,
            DeliveryRecordStatus.BOUNCED,
            DeliveryRecordStatus.COMPLAINED,
            DeliveryRecordStatus.OPENED,
            DeliveryRecordStatus.CLICKED,
        }
        event_counts = {}
        for label, event_type in {
            "delivered": "email.delivered",
            "bounced": "email.bounced",
            "failed": "email.failed",
            "complained": "email.complained",
            "opened": "email.opened",
            "clicked": "email.clicked",
        }.items():
            event_counts[label] = (
                DeliveryEvent.objects.filter(
                    delivery__campaign=campaign,
                    event_type=event_type,
                )
                .values("delivery_id")
                .distinct()
                .count()
            )
        job = campaign.delivery_jobs.order_by("-created_at").first()
        return Response(
            {
                "success": True,
                "data": {
                    "campaign_id": str(campaign.id),
                    "campaign_status": campaign.status,
                    "job": (
                        {
                            "id": str(job.id),
                            "status": job.status,
                            "scheduled_for": job.scheduled_for,
                            "started_at": job.started_at,
                            "completed_at": job.completed_at,
                            "error_summary": job.error_summary,
                        }
                        if job
                        else None
                    ),
                    "counts": {
                        "queued": records.filter(
                            status=DeliveryRecordStatus.QUEUED
                        ).count(),
                        "sent": records.filter(status__in=sent_states).count(),
                        "delivered": event_counts["delivered"],
                        "bounced": event_counts["bounced"],
                        "failed": records.filter(
                            status=DeliveryRecordStatus.FAILED
                        ).count(),
                        "complained": event_counts["complained"],
                        "opened": event_counts["opened"],
                        "clicked": event_counts["clicked"],
                        "suppressed": records.filter(
                            status=DeliveryRecordStatus.SUPPRESSED
                        ).count(),
                    },
                    "recipients": {
                        "total": recipient_count,
                        "limit": limit,
                        "offset": offset,
                        "items": recipient_records,
                    },
                },
            },
            status=status.HTTP_200_OK,
        )



class CampaignDesignView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CampaignDesignSaveSerializer

    @extend_schema(
        request=CampaignDesignSaveSerializer,
        responses={200: CampaignSerializer},
        summary="Save a validated EmailDesign version",
        description=(
            "Stores a new user-edit design version and makes it active. "
            "Saving a changed design invalidates prior reviewed/test-ready "
            "state by returning the campaign to generated."
        ),
    )
    def put(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignDesignSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            save_campaign_design(
                campaign,
                email_design=serializer.validated_data["email_design"],
                user=request.user,
            )
        except CampaignWorkflowError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )

        campaign.refresh_from_db()

        return Response(
            {
                "success": True,
                "data": CampaignSerializer(campaign).data,
            },
            status=status.HTTP_200_OK,
        )


class CampaignRenderView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CampaignRenderResponseSerializer

    @extend_schema(
        responses={200: CampaignRenderResponseSerializer},
        summary="Render the campaign's active EmailDesign",
        description=(
            "Renders from persisted BrandProfile, EmailDesign and asset "
            "inventory so clients do not manually assemble renderer inputs."
        ),
    )
    def get(self, request, campaign_id):
        campaign = _owned_campaign(request, campaign_id)

        try:
            render_result = render_campaign_email(campaign)
        except CampaignWorkflowError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except EmailRenderInputError as exc:
            return Response(
                {
                    "success": False,
                    "error": "Persisted campaign render input is invalid.",
                    "details": str(exc) if settings.DEBUG else None,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "success": True,
                "data": render_result,
            },
            status=status.HTTP_200_OK,
        )


class CampaignTestSendView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CampaignTestSendSerializer

    @extend_schema(
        request=CampaignTestSendSerializer,
        summary="Send the active campaign design as a test email",
        description=(
            "Renders the campaign from persisted state and sends one test "
            "recipient through the existing Resend delivery boundary."
        ),
    )
    def post(self, request, campaign_id):
        if not settings.RESEND_TEST_SEND_ENABLED:
            return Response(
                {
                    "success": False,
                    "error": "Test email sending is disabled.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        campaign = _owned_campaign(request, campaign_id)
        serializer = CampaignTestSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = send_campaign_test(
                campaign,
                to=serializer.validated_data["to"],
                idempotency_key=serializer.validated_data.get(
                    "idempotency_key"
                ),
            )
        except CampaignWorkflowError as exc:
            return Response(
                {
                    "success": False,
                    "error": str(exc),
                },
                status=status.HTTP_409_CONFLICT,
            )
        except EmailRenderInputError as exc:
            return Response(
                {
                    "success": False,
                    "error": "Persisted campaign render input is invalid.",
                    "details": str(exc) if settings.DEBUG else None,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                status=status.HTTP_502_BAD_GATEWAY,
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

            return Response(payload, status=response_status)

        campaign.refresh_from_db()

        return Response(
            {
                "success": True,
                "data": {
                    "campaign": CampaignSerializer(campaign).data,
                    **result,
                },
            },
            status=status.HTTP_200_OK,
        )
