from django.urls import include, path
from django.views.generic import TemplateView

urlpatterns = [
    path("", TemplateView.as_view(template_name="index.html"), name="home"),
    path("health", include("core.urls")),
    path("api/migrations/", include("migrationengine.urls")),
]
