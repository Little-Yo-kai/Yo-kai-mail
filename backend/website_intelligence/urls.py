from django.urls import path

from .views import WebsiteImportView

urlpatterns = [
    path("import/", WebsiteImportView.as_view(), name="website-import"),
]
