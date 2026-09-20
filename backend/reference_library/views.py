from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .library import get_public_reference_catalog
from .selector import select_reference
from .serializers import ReferenceSelectionRequestSerializer


class ReferenceLibraryListView(APIView):
    @extend_schema(
        summary="List curated internal reference directions",
        description=(
            "Lists Yo-kai Mail's reusable internal reference directions. "
            "The original inspiration images are not returned by this API."
        ),
    )
    def get(self, request):
        return Response(
            {
                "success": True,
                "data": get_public_reference_catalog(),
            },
            status=status.HTTP_200_OK,
        )


class ReferenceSelectView(APIView):
    serializer_class = ReferenceSelectionRequestSerializer

    @extend_schema(
        request=ReferenceSelectionRequestSerializer,
        summary="Choose an internal design reference",
        description=(
            "Selects a curated design direction from BrandProfile and "
            "CampaignBrief without making an AI provider call."
        ),
    )
    def post(self, request):
        serializer = ReferenceSelectionRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = select_reference(
            serializer.validated_data["brand_profile"],
            serializer.validated_data["campaign_brief"],
        )

        return Response(
            {"success": True, "data": result},
            status=status.HTTP_200_OK,
        )
