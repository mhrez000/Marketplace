"""API contract tests — the native apps depend on these payloads staying stable."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.core.management.commands.seed_demo import Command as Seed
from apps.galleries.models import Asset, Gallery
from apps.workspaces.models import Workspace

User = get_user_model()


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


class ApiTransactionFlowTests(TestCase):
    """Client quote->sign->deposit flow over the API, mirroring the web portal."""

    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def _pending_quote(self, client):
        """Find a client enquiry that has a SENT/DRAFT quote to act on."""
        for e in client.get(reverse("api:enquiries")).data:
            for q in e["quotes"]:
                if q["status"] in ("sent", "draft") and not q["is_expired"]:
                    return q
        return None

    def test_enquiries_include_quotes(self):
        c = self._auth("northcote@lens.test")
        data = c.get(reverse("api:enquiries")).data
        self.assertTrue(any("quotes" in e for e in data))

    def test_accept_quote_then_sign_then_pay(self):
        c = self._auth("northcote@lens.test")
        quote = self._pending_quote(c)
        self.assertIsNotNone(quote, "seed should leave northcote a pending quote")

        accept = c.post(reverse("api:quote_accept", args=[quote["id"]]))
        self.assertEqual(accept.status_code, 201)
        bid = accept.data["id"]
        self.assertEqual(accept.data["status"], "contract_sent")
        self.assertEqual(accept.data["next_action"], "sign")
        self.assertIsNotNone(accept.data["contract"])

        sign = c.post(reverse("api:booking_sign", args=[bid]), {"name": "Northcote Realty"})
        self.assertEqual(sign.status_code, 200)
        self.assertEqual(sign.data["status"], "contract_signed")
        self.assertEqual(sign.data["next_action"], "pay_deposit")

        pay = c.post(reverse("api:booking_pay_deposit", args=[bid]))
        self.assertEqual(pay.status_code, 200)
        self.assertIn(pay.data["status"], ("deposit_paid", "confirmed"))
        self.assertIsNone(pay.data["next_action"])

    def test_sign_requires_name(self):
        c = self._auth("northcote@lens.test")
        quote = self._pending_quote(c)
        bid = c.post(reverse("api:quote_accept", args=[quote["id"]])).data["id"]
        self.assertEqual(c.post(reverse("api:booking_sign", args=[bid]), {"name": ""}).status_code, 400)

    def test_decline_quote(self):
        c = self._auth("northcote@lens.test")
        quote = self._pending_quote(c)
        resp = c.post(reverse("api:quote_decline", args=[quote["id"]]))
        self.assertEqual(resp.status_code, 200)
        # the same quote should no longer be pending
        self.assertIsNone(next((q for e in c.get(reverse("api:enquiries")).data
                                for q in e["quotes"] if q["id"] == quote["id"]
                                and q["status"] in ("sent", "draft")), None))

    def test_cannot_act_on_others_booking(self):
        owner = self._auth("northcote@lens.test")
        quote = self._pending_quote(owner)
        bid = owner.post(reverse("api:quote_accept", args=[quote["id"]])).data["id"]
        intruder = self._auth("sam@lens.test")
        self.assertEqual(intruder.post(reverse("api:booking_pay_deposit", args=[bid])).status_code, 404)


class ApiGalleryTests(TestCase):
    def setUp(self):
        creative = User.objects.create_user(email="cr@t.com", password="x")
        User.objects.create_user(email="cl@t.com", password="lens12345")
        self.ws = Workspace.objects.create(owner=creative, business_name="S", is_published=True)
        self.client_user = User.objects.get(email="cl@t.com")
        booking = Booking.objects.create(client=self.client_user, workspace=self.ws)
        self.gallery = Gallery.objects.create(booking=booking, title="Wedding gallery", is_delivered=True)
        self.asset = Asset.objects.create(gallery=self.gallery, title="Shot 1")
        self.booking = booking
        self.api = APIClient()
        token = self.api.post(reverse("api:login"),
                              {"email": "cl@t.com", "password": "lens12345"}).data["token"]
        self.api.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def test_gallery_detail_lists_assets(self):
        r = self.api.get(reverse("api:gallery_detail", args=[self.gallery.id]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["assets"]), 1)
        self.assertEqual(r.data["assets"][0]["title"], "Shot 1")

    def test_asset_favourite_toggles(self):
        url = reverse("api:asset_favourite", args=[self.asset.id])
        self.assertTrue(self.api.post(url).data["is_favourite"])
        self.assertFalse(self.api.post(url).data["is_favourite"])

    def test_gallery_scoped_to_owner(self):
        other = APIClient()
        User.objects.create_user(email="other@t.com", password="lens12345")
        tok = other.post(reverse("api:login"),
                         {"email": "other@t.com", "password": "lens12345"}).data["token"]
        other.credentials(HTTP_AUTHORIZATION=f"Token {tok}")
        self.assertEqual(other.get(reverse("api:gallery_detail", args=[self.gallery.id])).status_code, 404)

    def test_booking_detail_includes_galleries(self):
        r = self.api.get(reverse("api:booking_detail", args=[str(self.booking.id)]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data["galleries"]), 1)


class ApiMessagingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_threads_requires_auth(self):
        self.assertEqual(APIClient().get(reverse("api:threads")).status_code, 401)

    def test_thread_list_and_detail(self):
        c = self._auth("harper@lens.test")  # a creative with seeded conversations
        threads = c.get(reverse("api:threads"))
        self.assertEqual(threads.status_code, 200)
        self.assertGreaterEqual(len(threads.data), 1)
        first = threads.data[0]
        for key in ("id", "other", "last_message", "unread"):
            self.assertIn(key, first)
        detail = c.get(reverse("api:thread_detail", args=[first["id"]]))
        self.assertEqual(detail.status_code, 200)
        self.assertIn("messages", detail.data)

    def test_send_message(self):
        c = self._auth("harper@lens.test")
        tid = c.get(reverse("api:threads")).data[0]["id"]
        before = len(c.get(reverse("api:thread_detail", args=[tid])).data["messages"])
        sent = c.post(reverse("api:thread_detail", args=[tid]), {"body": "On it — thanks!"})
        self.assertEqual(sent.status_code, 201)
        self.assertTrue(sent.data["sender_is_me"])
        after = len(c.get(reverse("api:thread_detail", args=[tid])).data["messages"])
        self.assertEqual(after, before + 1)

    def test_empty_message_rejected(self):
        c = self._auth("harper@lens.test")
        tid = c.get(reverse("api:threads")).data[0]["id"]
        self.assertEqual(c.post(reverse("api:thread_detail", args=[tid]), {"body": "  "}).status_code, 400)

    def test_non_participant_forbidden(self):
        owner = self._auth("harper@lens.test")
        tid = owner.get(reverse("api:threads")).data[0]["id"]
        intruder = self._auth("juniper@lens.test")  # unrelated creative
        self.assertEqual(intruder.get(reverse("api:thread_detail", args=[tid])).status_code, 403)
