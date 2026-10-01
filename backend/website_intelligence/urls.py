from django.urls import path

from .views import WebsiteImportView, WebsiteCrawlImportView


urlpatterns = [
    path(
        "import/",
        WebsiteImportView.as_view(),
        name="website-import",
    ),
    path(
        "import/crawl/",
        WebsiteCrawlImportView.as_view(),
        name="website-import-crawl",
    ),
]