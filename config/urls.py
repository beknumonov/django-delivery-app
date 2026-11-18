from django.contrib import admin
from django.urls import include, path

from notes import health

urlpatterns = [
    # Django admin UI.
    path("admin/", admin.site.urls),
    # Mount the notes app's routes under /api/.
    path("api/", include("notes.urls")),
    # Kubernetes probes (wired up in Module 7). Kept outside /api/ because
    # they are for the platform, not for API clients.
    path("healthz/live", health.live, name="health-live"),
    path("healthz/ready", health.ready, name="health-ready"),
    path("healthz/startup", health.startup, name="health-startup"),
    # Adds /metrics: request counts, latency histograms, DB query stats in
    # Prometheus format. Scraped in Module 11 (canary) and Module 13 (alerts).
    path("", include("django_prometheus.urls")),
]
