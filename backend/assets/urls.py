from django.urls import path

from .views import (
    AssetDetailView,
    AssetImportView,
    AssetListView,
    AssetPromoteView,
)


urlpatterns = [
    path("import/", AssetImportView.as_view(), name="asset-import"),
    path("", AssetListView.as_view(), name="asset-list"),
    path("<uuid:asset_id>/", AssetDetailView.as_view(), name="asset-detail"),
    path("<uuid:asset_id>/promote/", AssetPromoteView.as_view(), name="asset-promote"),
]