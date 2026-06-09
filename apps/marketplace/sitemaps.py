from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.workspaces.models import Workspace

from .geo import SERVICES, SUBURBS


class StaticSitemap(Sitemap):
    priority = 0.6
    changefreq = "weekly"

    def items(self):
        return ["marketplace:home", "marketplace:search", "marketplace:how_it_works",
                "marketplace:pricing", "marketplace:for_creatives", "marketplace:browse"]

    def location(self, name):
        return reverse(name)


class ProfileSitemap(Sitemap):
    priority = 0.8
    changefreq = "weekly"

    def items(self):
        return Workspace.objects.filter(is_published=True)

    def location(self, ws):
        return reverse("marketplace:profile", args=[ws.slug])

    def lastmod(self, ws):
        return ws.updated_at


class SuburbServiceSitemap(Sitemap):
    """Every service × suburb landing page — the programmatic SEO surface."""
    priority = 0.7
    changefreq = "weekly"

    def items(self):
        return [(svc, sub[1]) for svc in SERVICES for sub in SUBURBS]

    def location(self, item):
        service, suburb_slug = item
        return reverse("marketplace:suburb_service", args=[service, suburb_slug])


SITEMAPS = {
    "static": StaticSitemap,
    "profiles": ProfileSitemap,
    "locations": SuburbServiceSitemap,
}
