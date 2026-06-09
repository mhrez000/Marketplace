from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.marketplace.models import Favourite
from apps.profiles.models import CreativeProfile
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
