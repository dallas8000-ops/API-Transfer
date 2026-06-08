from django.urls import path

from .views import IssueLicenseView, RevokeLicenseView, ValidateLicenseView

urlpatterns = [
    path("issue", IssueLicenseView.as_view(), name="license-issue"),
    path("validate", ValidateLicenseView.as_view(), name="license-validate"),
    path("revoke", RevokeLicenseView.as_view(), name="license-revoke"),
]
