from django.urls import path

from .views import ReferenceLibraryListView, ReferenceSelectView

urlpatterns = [
    path("", ReferenceLibraryListView.as_view(), name="reference-library-list"),
    path("select/", ReferenceSelectView.as_view(), name="reference-library-select"),
]
