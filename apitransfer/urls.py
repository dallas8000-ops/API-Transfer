from django.urls import include, path, re_path
from django.views.generic import TemplateView

# API/system routes are matched first. Any other path falls through to the SPA
# shell so client-side routes (e.g. /pricing, /console) work on a hard refresh.
# The shell template resolves to frontend_dist/index.html when the React app has
# been built, and to the legacy public/index.html otherwise (see settings).
spa = TemplateView.as_view(template_name="index.html")

urlpatterns = [
    path("health", include("core.urls")),
    path("api/migrations/", include("migrationengine.urls")),
    path("api/billing/", include("billing.urls")),
    path("api/license/", include("licenses.urls")),
    path("", spa, name="home"),
    # Catch-all for SPA client routes; excludes api/, health, and static/ paths.
    re_path(r"^(?!api/|health|static/).*$", spa, name="spa"),
]
