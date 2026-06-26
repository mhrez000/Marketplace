"""HTTP helpers shared across views."""
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def safe_redirect(request, candidate, fallback):
    """Redirect to a user-supplied `candidate` URL only if it points back at this
    site (same host, safe scheme). Otherwise fall back to `fallback`. Prevents
    open redirects where a `next=`/Referer value sends users to an attacker host.
    """
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(candidate)
    return redirect(fallback)
