from django.db import connection
from django.http import JsonResponse


def live(request):
    """Liveness: is the Python process alive and answering?

    NEVER touches the database on purpose. If Postgres goes down and liveness
    checked it, Kubernetes would restart EVERY pod at once — that doesn't fix
    Postgres and turns a DB outage into a restart storm. Restarting only helps
    when the process itself is broken (deadlock, stuck worker).
    """
    return JsonResponse({"status": "ok"})


def ready(request):
    """Readiness: can this pod serve real requests right now?

    Runs the cheapest possible query. If the DB is unreachable we return 503:
    Kubernetes takes the pod out of load balancing (no restart) and puts it
    back automatically when the DB recovers. Probes only look at the status
    code, so the code — not the JSON — is what matters.
    """
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception:
        return JsonResponse({"status": "db-unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def startup(request):
    """Startup: has the app finished booting (migrations applied, caches warm)?

    A stub for now. It protects slow-starting pods from being killed by the
    liveness probe before they are up.
    """
    return JsonResponse({"status": "ok"})
