import logging

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema, OpenApiParameter
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AssetRecord
from .serializers import AssetImportRequestSerializer, AssetRecordSerializer
from .services.pipeline import process_asset
from .services.promotion import InvalidPromotionError, promote_asset

logger = logging.getLogger(__name__)


class AssetImportView(APIView):
    """
    POST /api/assets/import/
    Creates an AssetRecord for a discovered/uploaded image and runs it
    through fetch -> SSRF check -> validate -> dedup -> temp storage.
    This is what Website Intelligence's discovered images (or a reference
    upload) turn into before anything downstream can use them.
    """

    @extend_schema(
        request=AssetImportRequestSerializer,
        responses=AssetRecordSerializer,
        summary="Import and validate an image as an AssetRecord",
        description=(
            "Fetches original_url (SSRF-checked), validates it's a real "
            "supported image, deduplicates by URL/content hash, and stores "
            "it in temporary storage. Failures come back as an explicit "
            "'failed' or 'unusable' status on the returned record, not an "
            "HTTP error - the record is still created either way."
        ),
    )
    def post(self, request):
        serializer = AssetImportRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        asset = AssetRecord.objects.create(
            owner_reference=data["owner_reference"],
            original_url=data["original_url"],
            source=data.get("source", ""),
        )

        try:
            process_asset(asset)
        except Exception:
            # fetch_and_validate already converts expected failure modes
            # (network errors, SSRF blocks, bad images) into
            # failed/unusable status on the record itself - reaching here
            # means something unexpected broke (a bug, a DB error, disk
            # full, etc.), not a normal rejected asset.
            logger.exception("Unexpected error processing asset %s", asset.asset_id)
            asset.refresh_from_db()
            return Response(
                {
                    "success": False,
                    "error": "Asset import failed unexpectedly.",
                    "data": AssetRecordSerializer(asset).data,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        asset.refresh_from_db()
        return Response(
            {"success": True, "data": AssetRecordSerializer(asset).data},
            status=status.HTTP_201_CREATED,
        )


class AssetDetailView(APIView):
    """GET /api/assets/{asset_id}/"""

    @extend_schema(responses=AssetRecordSerializer, summary="Get one asset's status")
    def get(self, request, asset_id):
        asset = get_object_or_404(AssetRecord, asset_id=asset_id)
        return Response({"success": True, "data": AssetRecordSerializer(asset).data})


class AssetListView(APIView):
    """GET /api/assets/?owner_reference=campaign-123"""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="owner_reference",
                required=False,
                description="Filter to assets belonging to this campaign/brand owner.",
            )
        ],
        responses=AssetRecordSerializer(many=True),
        summary="List assets, optionally filtered by owner",
    )
    def get(self, request):
        queryset = AssetRecord.objects.all()

        owner_reference = request.query_params.get("owner_reference")
        if owner_reference:
            queryset = queryset.filter(owner_reference=owner_reference)

        return Response(
            {"success": True, "data": AssetRecordSerializer(queryset, many=True).data}
        )


class AssetPromoteView(APIView):
    """
    POST /api/assets/{asset_id}/promote/
    Moves a temporary asset to persistent storage. Intended to be called
    when a campaign is approved or saved for sending.
    """

    @extend_schema(
        request=None,
        responses=AssetRecordSerializer,
        summary="Promote a temporary asset to persistent storage",
    )
    def post(self, request, asset_id):
        asset = get_object_or_404(AssetRecord, asset_id=asset_id)

        try:
            promote_asset(asset)
        except InvalidPromotionError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_409_CONFLICT,
            )
        except Exception:
            logger.exception("Unexpected error promoting asset %s", asset_id)
            return Response(
                {"success": False, "error": "Asset promotion failed unexpectedly."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        asset.refresh_from_db()
        return Response({"success": True, "data": AssetRecordSerializer(asset).data})
