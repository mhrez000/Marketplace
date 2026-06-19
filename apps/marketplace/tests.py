import json
import re

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings.models import Booking
from apps.marketplace.models import Favourite
from apps.profiles.models import CreativeProfile
from apps.reviews.models import Review
from apps.workspaces.models import Workspace

User = get_user_model()


class FavouriteTests(TestCase):
    def setUp(self):
        creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=creative, business_name="Saved Studio", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def test_toggle_favourite_adds_then_removes(self):
        self.client.force_login(self.client_user)
        url = f"/p/{self.ws.slug}/favourite/"
        self.client.post(url, SERVER_NAME="localhost")
        self.assertTrue(Favourite.objects.filter(client=self.client_user, workspace=self.ws).exists())
        self.client.post(url, SERVER_NAME="localhost")
        self.assertFalse(Favourite.objects.filter(client=self.client_user, workspace=self.ws).exists())

    def test_favourite_requires_login(self):
        r = self.client.post(f"/p/{self.ws.slug}/favourite/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 302)  # redirected to login
        self.assertFalse(Favourite.objects.exists())


class PublicProfileVisibilityTests(TestCase):
    """The 'View public page' link must reach the profile, not bounce to a 404.
    The owner can preview their own page before publishing; others can't."""

    def setUp(self):
        self.owner = User.objects.create_user(email="owner@t.com", password="x")
        self.other = User.objects.create_user(email="nosy@t.com", password="x")
        self.ws = Workspace.objects.create(owner=self.owner, business_name="Draft Studio",
                                           is_published=False)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def test_owner_can_preview_unpublished_page(self):
        self.client.force_login(self.owner)
        r = self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)

    def test_unpublished_hidden_from_others(self):
        self.assertEqual(self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost").status_code, 404)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost").status_code, 404)

    def test_published_page_is_public(self):
        self.ws.is_published = True
        self.ws.save(update_fields=["is_published"])
        self.assertEqual(self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost").status_code, 200)


class StaticPageTests(TestCase):
    def test_legal_and_support_pages_render(self):
        for path, needle in [("/privacy/", "Privacy Policy"),
                             ("/terms/", "Terms of Service"),
                             ("/help/", "Help")]:
            r = self.client.get(path, SERVER_NAME="localhost")
            self.assertEqual(r.status_code, 200, path)
            self.assertContains(r, needle)

    def test_footer_links_resolve(self):
        from django.urls import reverse
        for name in ["marketplace:privacy", "marketplace:terms", "marketplace:help"]:
            self.assertTrue(reverse(name))


class SeoTests(TestCase):
    def setUp(self):
        self.creative = User.objects.create_user(email="cr@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="Aperture Co", is_published=True)
        self.profile = CreativeProfile.objects.create(
            workspace=self.ws, primary_category="weddings", headline="Editorial wedding photography",
            suburb="Carlton", city="Melbourne", starting_price=2400)
        b = Booking.objects.create(client=self.client_user, workspace=self.ws)
        # An adversarial body (quotes + symbols) must not break the JSON-LD.
        Review.objects.create(booking=b, client=self.client_user, workspace=self.ws,
                              rating=5, title="Amazing", body='Best day ever — "quotes" & symbols')

    def _jsonld(self, html):
        return re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)

    def test_home_has_canonical_og_and_schema(self):
        html = self.client.get("/", SERVER_NAME="localhost").content.decode()
        self.assertIn('<link rel="canonical"', html)
        self.assertIn('property="og:title"', html)
        self.assertIn('property="og:image"', html)
        self.assertIn('name="twitter:card"', html)
        types = {json.loads(b)["@type"] for b in self._jsonld(html)}
        self.assertIn("Organization", types)
        self.assertIn("WebSite", types)

    def test_profile_jsonld_valid_with_rating(self):
        r = self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        blocks = self._jsonld(r.content.decode())
        self.assertTrue(blocks)
        data = json.loads(blocks[0])  # must parse despite quotes/symbols in the review body
        self.assertEqual(data["@type"], "ProfessionalService")
        self.assertEqual(data["aggregateRating"]["reviewCount"], "1")
        self.assertEqual(len(data["review"]), 1)

    def test_every_public_page_has_canonical(self):
        from django.urls import reverse
        for name in ["marketplace:home", "marketplace:search", "marketplace:pricing",
                     "marketplace:how_it_works", "marketplace:for_creatives",
                     "marketplace:browse", "marketplace:privacy", "marketplace:terms",
                     "marketplace:help"]:
            html = self.client.get(reverse(name), SERVER_NAME="localhost").content.decode()
            self.assertIn('<link rel="canonical"', html, name)

    def test_filtered_search_is_noindex_but_bare_is_not(self):
        bare = self.client.get("/search/", SERVER_NAME="localhost").content.decode()
        self.assertNotIn("noindex", bare)
        filtered = self.client.get("/search/?q=Weddings", SERVER_NAME="localhost").content.decode()
        self.assertIn("noindex", filtered)


class SeoGeoTests(TestCase):
    def setUp(self):
        from decimal import Decimal
        from apps.profiles.models import Package, Service
        creative = User.objects.create_user(email="c@t.com", password="x")
        self.ws = Workspace.objects.create(owner=creative, business_name="Fitzroy Films", is_published=True)
        # Base in Fitzroy, 40km radius -> serves Carlton (~2km away).
        CreativeProfile.objects.create(
            workspace=self.ws, primary_category="weddings", bio="Hi", suburb="Fitzroy",
            starting_price=Decimal("2000"), service_radius_km=40,
            latitude=-37.7980, longitude=144.9784)
        svc = Service.objects.create(workspace=self.ws, category="weddings", title="W")
        Package.objects.create(service=svc, name="P", base_price=Decimal("2000"))

    def test_geo_matches_within_radius(self):
        from apps.marketplace.geo import creatives_serving
        carlton = creatives_serving("carlton", category="weddings")
        self.assertIn(self.ws.id, [p.workspace_id for p in carlton])

    def test_geo_excludes_far_suburb(self):
        from apps.marketplace.geo import creatives_serving
        geelong = creatives_serving("geelong", category="weddings")  # ~70km
        self.assertNotIn(self.ws.id, [p.workspace_id for p in geelong])

    def test_suburb_service_page_renders(self):
        r = self.client.get("/wedding-photographer/fitzroy/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Wedding Photographers in Fitzroy")
        self.assertContains(r, "BreadcrumbList")

    def test_unknown_service_404(self):
        r = self.client.get("/not-a-service/fitzroy/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 404)

    def test_profile_route_not_shadowed(self):
        r = self.client.get(f"/p/{self.ws.slug}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)

    def test_sitemap_and_robots(self):
        self.assertEqual(self.client.get("/sitemap.xml", SERVER_NAME="localhost").status_code, 200)
        self.assertEqual(self.client.get("/robots.txt", SERVER_NAME="localhost").status_code, 200)
