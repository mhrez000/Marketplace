"""API contract tests — the native apps depend on these payloads staying stable."""
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.management.commands.seed_demo import Command as Seed


class ApiAuthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def setUp(self):
        self.client = APIClient()

    def test_register_returns_token(self):
        resp = self.client.post(reverse("api:register"),
                                {"email": "new@lens.test", "password": "lens12345", "name": "New Person"})
        self.assertEqual(resp.status_code, 201)
        self.assertIn("token", resp.data)
        self.assertEqual(resp.data["user"]["email"], "new@lens.test")

    def test_register_rejects_duplicate(self):
        resp = self.client.post(reverse("api:register"),
                                {"email": "olivia@lens.test", "password": "lens12345"})
        self.assertEqual(resp.status_code, 400)

    def test_login_returns_token(self):
        resp = self.client.post(reverse("api:login"),
                                {"email": "olivia@lens.test", "password": "lens12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.data)

    def test_login_rejects_bad_password(self):
        resp = self.client.post(reverse("api:login"),
                                {"email": "olivia@lens.test", "password": "wrong"})
        self.assertEqual(resp.status_code, 400)

    def test_me_requires_auth(self):
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)

    def test_me_returns_profile(self):
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        resp = self.client.get(reverse("api:me"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], "olivia@lens.test")


class ApiCreativesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def setUp(self):
        self.client = APIClient()

    def test_creatives_list_is_public(self):
        resp = self.client.get(reverse("api:creatives"))
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.data), 0)
        first = resp.data[0]
        for key in ("slug", "business_name", "headline", "starting_price", "avg_rating"):
            self.assertIn(key, first)

    def test_creatives_filter_by_category(self):
        resp = self.client.get(reverse("api:creatives"), {"category": "real_estate"})
        self.assertEqual(resp.status_code, 200)
        for item in resp.data:
            self.assertEqual(item["primary_category"], "real_estate")

    def test_creative_detail(self):
        slug = self.client.get(reverse("api:creatives")).data[0]["slug"]
        resp = self.client.get(reverse("api:creative_detail", args=[slug]))
        self.assertEqual(resp.status_code, 200)
        for key in ("bio", "packages", "reviews", "styles"):
            self.assertIn(key, resp.data)


class ApiBookingsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def setUp(self):
        self.client = APIClient()
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_bookings_requires_auth(self):
        anon = APIClient()
        self.assertEqual(anon.get(reverse("api:bookings")).status_code, 401)

    def test_bookings_list(self):
        resp = self.client.get(reverse("api:bookings"))
        self.assertEqual(resp.status_code, 200)

    def test_enquiry_create_and_list(self):
        slug = self.client.get(reverse("api:creatives")).data[0]["slug"]
        create = self.client.post(reverse("api:enquiries"), {
            "workspace": slug, "event_type": "weddings",
            "message": "Available on my date?", "location": "Fitzroy",
        })
        self.assertEqual(create.status_code, 201)
        listing = self.client.get(reverse("api:enquiries"))
        self.assertEqual(listing.status_code, 200)
        self.assertGreaterEqual(len(listing.data), 1)
