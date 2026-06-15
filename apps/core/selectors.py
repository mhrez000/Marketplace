"""Shared query helpers used across apps."""
from django.db.models import Avg, Count


def get_active_workspace(user):
    """The workspace a logged-in creative is currently acting as (their first
    owned workspace). Returns None for pure clients."""
    if not user.is_authenticated:
        return None
    return user.owned_workspaces.first()


def dashboard_shell(user):
    """Pick the base layout for pages shared by creatives and clients (Messages,
    Settings): creatives get the dashboard chrome, clients the public site.

    Returns (workspace_or_None, base_template_name)."""
    ws = get_active_workspace(user)
    return ws, ("base_app.html" if ws else "base_public.html")


def annotate_ratings(profile_qs):
    """Annotate a CreativeProfile queryset with avg rating + review count."""
    return profile_qs.annotate(
        avg_rating=Avg("workspace__reviews__rating"),
        review_count=Count("workspace__reviews", distinct=True),
    )
