from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer /healthz before host validation or SSL redirects.

    Platform health checks (Fly's Consul) probe the machine directly with an
    internal IP as the Host header, which ALLOWED_HOSTS would 400. This sits at
    the top of the middleware stack and short-circuits the probe."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/healthz":
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
