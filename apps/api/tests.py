"""API contract tests — the native apps depend on these payloads staying stable."""
import io
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient


def _png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (47, 65, 86)).save(buf, "PNG")
    return buf.getvalue()

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

    def test_register_and_remove_device(self):
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        reg = self.client.post(reverse("api:devices"), {"token": "abc123", "platform": "ios"})
        self.assertEqual(reg.status_code, 201)
        from apps.notifications.models import DeviceToken
        self.assertTrue(DeviceToken.objects.filter(token="abc123").exists())
        # push is inert without FCM_SERVER_KEY — notifying never raises
        from apps.notifications.models import notify
        notify(DeviceToken.objects.get(token="abc123").user, "Test push", url="/x")
        self.assertEqual(self.client.delete(reverse("api:devices"), {"token": "abc123"},
                                            format="json").status_code, 204)
        self.assertFalse(DeviceToken.objects.filter(token="abc123").exists())

    def test_me_returns_profile(self):
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        resp = self.client.get(reverse("api:me"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["email"], "olivia@lens.test")

    def test_register_rejects_weak_password(self):
        """F2: API register must run password validators (create_user doesn't)."""
        resp = self.client.post(reverse("api:register"),
                                {"email": "weak@lens.test", "password": "1"})
        self.assertEqual(resp.status_code, 400)
        from django.contrib.auth import get_user_model
        self.assertFalse(get_user_model().objects.filter(email="weak@lens.test").exists())

    def test_logout_revokes_token(self):
        """F7: logging out deletes the token so it can't be replayed."""
        from rest_framework.authtoken.models import Token
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        self.assertEqual(self.client.post(reverse("api:logout")).status_code, 204)
        self.assertFalse(Token.objects.filter(key=token).exists())
        # the revoked token no longer authenticates
        self.assertEqual(self.client.get(reverse("api:me")).status_code, 401)


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


class ApiCreativeProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_get_and_update_profile(self):
        c = self._auth("harper@lens.test")
        got = c.get(reverse("api:my_profile"))
        self.assertEqual(got.status_code, 200)
        self.assertIn("headline", got.data)

        upd = c.put(reverse("api:my_profile"),
                    {"headline": "Editorial wedding stories", "styles": ["film", "candid"],
                     "starting_price": "2750"}, format="json")
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.data["headline"], "Editorial wedding stories")
        self.assertEqual(upd.data["styles"], ["film", "candid"])
        self.assertEqual(upd.data["starting_price"], "2750.00")

    def test_client_has_no_profile(self):
        self.assertEqual(self._auth("olivia@lens.test").get(reverse("api:my_profile")).status_code, 403)

    def test_package_crud(self):
        c = self._auth("harper@lens.test")
        before = len(c.get(reverse("api:my_profile")).data["packages"])
        created = c.post(reverse("api:packages"),
                         {"name": "Engagement", "base_price": "950",
                          "inclusions": ["50 photos", "Gallery"]}, format="json")
        self.assertEqual(created.status_code, 201)
        pid = created.data["id"]
        self.assertEqual(created.data["base_price"], "950.00")
        self.assertEqual(created.data["inclusions"], ["50 photos", "Gallery"])
        # appears in the profile payload
        self.assertEqual(len(c.get(reverse("api:my_profile")).data["packages"]), before + 1)
        # edit
        upd = c.put(reverse("api:package_detail", args=[pid]), {"base_price": "1100"}, format="json")
        self.assertEqual(upd.data["base_price"], "1100.00")
        # delete
        self.assertEqual(c.delete(reverse("api:package_detail", args=[pid])).status_code, 204)
        self.assertEqual(len(c.get(reverse("api:my_profile")).data["packages"]), before)

    def test_client_cannot_manage_packages(self):
        self.assertEqual(
            self._auth("olivia@lens.test").post(reverse("api:packages"),
                                                {"name": "X", "base_price": "1"}).status_code, 403)

    def test_analytics_for_creative(self):
        a = self._auth("harper@lens.test").get(reverse("api:analytics"))
        self.assertEqual(a.status_code, 200)
        for key in ("paid", "pipeline", "funnel", "trend", "profile_views"):
            self.assertIn(key, a.data)

    def test_analytics_forbidden_for_client(self):
        self.assertEqual(self._auth("olivia@lens.test").get(reverse("api:analytics")).status_code, 403)

    def test_advance_production(self):
        c = self._auth("harper@lens.test")
        target = next((b for b in c.get(reverse("api:bookings")).data
                       if b["status"] in ("confirmed", "planning")), None)
        if not target:
            self.skipTest("no confirmed booking to advance")
        resp = c.post(reverse("api:booking_advance", args=[target["id"]]),
                      {"step": "shoot_completed"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["status"], "shoot_completed")
        self.assertEqual(resp.data["creative_step"], "start_editing")

    def test_advance_forbidden_for_client(self):
        client = self._auth("olivia@lens.test")
        bid = client.get(reverse("api:bookings")).data[0]["id"]
        self.assertEqual(
            client.post(reverse("api:booking_advance", args=[bid]), {"step": "shoot_completed"}).status_code, 403)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ApiUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_creative_uploads_photos(self):
        c = self._auth("harper@lens.test")
        bid = c.get(reverse("api:bookings")).data[0]["id"]
        img = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
        resp = c.post(reverse("api:gallery_upload", args=[bid]), {"image": img}, format="multipart")
        self.assertEqual(resp.status_code, 201)
        self.assertGreaterEqual(len(resp.data["assets"]), 1)
        self.assertTrue(resp.data["assets"][0]["image_url"])
        self.assertFalse(resp.data["is_link_delivery"])  # an in-app (uploaded) gallery

    def test_client_cannot_upload(self):
        c = self._auth("olivia@lens.test")
        bid = c.get(reverse("api:bookings")).data[0]["id"]
        img = SimpleUploadedFile("x.png", _png_bytes(), content_type="image/png")
        self.assertEqual(
            c.post(reverse("api:gallery_upload", args=[bid]), {"image": img}, format="multipart").status_code, 403)


class ApiPolishTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_availability_block_unblock(self):
        c = self._auth("harper@lens.test")
        self.assertEqual(c.get(reverse("api:availability")).status_code, 200)
        blocked = c.post(reverse("api:availability_block"), {"date": "2099-12-25"})
        self.assertEqual(blocked.status_code, 200)
        self.assertIn("2099-12-25", blocked.data["blocked"])
        un = c.post(reverse("api:availability_unblock"), {"date": "2099-12-25"})
        self.assertNotIn("2099-12-25", un.data["blocked"])

    def test_availability_forbidden_for_client(self):
        self.assertEqual(self._auth("olivia@lens.test").get(reverse("api:availability")).status_code, 403)

    def test_review_requires_complete(self):
        client = self._auth("olivia@lens.test")
        # find an incomplete booking
        bk = next((b for b in client.get(reverse("api:bookings")).data
                   if b["status"] != "completed"), None)
        if bk:
            self.assertEqual(
                client.post(reverse("api:booking_review", args=[bk["id"]]), {"rating": 5}).status_code, 400)

    def test_review_on_completed_booking(self):
        client = self._auth("olivia@lens.test")
        bk = next((b for b in client.get(reverse("api:bookings")).data
                   if b["status"] == "completed"), None)
        if not bk:
            self.skipTest("no completed booking for olivia in seed")
        resp = client.post(reverse("api:booking_review", args=[bk["id"]]),
                           {"rating": 5, "title": "Amazing", "body": "Loved it"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["review"]["rating"], 5)
        self.assertFalse(resp.data["awaiting_review"])

    def test_raise_dispute(self):
        client = self._auth("olivia@lens.test")
        bid = client.get(reverse("api:bookings")).data[0]["id"]
        resp = client.post(reverse("api:booking_dispute", args=[bid]),
                           {"reason": "other", "detail": "Test concern"})
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.data["dispute"])
        self.assertTrue(len(resp.data["dispute_reasons"]) > 0)

    def test_availability_exposes_ical_url(self):
        data = self._auth("harper@lens.test").get(reverse("api:availability")).data
        self.assertIn("ical_url", data)
        self.assertIn("/calendar/", data["ical_url"])

    def test_ical_feed_renders(self):
        from apps.core.selectors import get_active_workspace
        ws = get_active_workspace(User.objects.get(email="harper@lens.test"))
        r = self.client.get(f"/calendar/{ws.ical_token}.ics", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["content-type"], "text/calendar; charset=utf-8")
        self.assertIn(b"BEGIN:VCALENDAR", r.content)
        self.assertIn(b"END:VCALENDAR", r.content)

    def test_ical_feed_bad_token_404(self):
        import uuid as _uuid
        self.assertEqual(
            self.client.get(f"/calendar/{_uuid.uuid4()}.ics", SERVER_NAME="localhost").status_code, 404)


class ApiFavouritesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def setUp(self):
        self.client = APIClient()
        token = self.client.post(reverse("api:login"),
                                 {"email": "olivia@lens.test", "password": "lens12345"}).data["token"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

    def _is_listed(self, slug):
        return any(c["slug"] == slug for c in self.client.get(reverse("api:favourites")).data)

    def test_toggle_and_list_favourites(self):
        slug = self.client.get(reverse("api:creatives")).data[0]["slug"]
        before = self.client.get(reverse("api:creative_detail", args=[slug])).data["is_favourited"]

        toggled = self.client.post(reverse("api:creative_favourite", args=[slug])).data["is_favourited"]
        self.assertEqual(toggled, not before)
        # detail + list both reflect the new state
        self.assertEqual(
            self.client.get(reverse("api:creative_detail", args=[slug])).data["is_favourited"], toggled)
        self.assertEqual(self._is_listed(slug), toggled)

        # toggling again returns to the original state
        again = self.client.post(reverse("api:creative_favourite", args=[slug])).data["is_favourited"]
        self.assertEqual(again, before)
        self.assertEqual(self._is_listed(slug), before)

    def test_favourite_requires_auth(self):
        self.assertEqual(APIClient().get(reverse("api:favourites")).status_code, 401)


class ApiLeadsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Seed().handle(quiet=True)

    def _auth(self, email):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": email, "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        return c

    def test_me_marks_creatives(self):
        creative = self._auth("harper@lens.test").get(reverse("api:me")).data
        self.assertTrue(creative["is_creative"])
        self.assertIsNotNone(creative["workspace"])
        client = self._auth("olivia@lens.test").get(reverse("api:me")).data
        self.assertFalse(client["is_creative"])
        self.assertIsNone(client["workspace"])

    def test_leads_listed_for_creative_only(self):
        creative = self._auth("harper@lens.test")
        leads = creative.get(reverse("api:leads"))
        self.assertEqual(leads.status_code, 200)
        self.assertGreaterEqual(len(leads.data), 1)
        self.assertIn("client_name", leads.data[0])
        # a pure client has no leads
        self.assertEqual(self._auth("olivia@lens.test").get(reverse("api:leads")).data, [])

    def test_send_quote_appears_for_client(self):
        creative = self._auth("harper@lens.test")
        # find a lead without an accepted/sent quote to keep it clean
        lead = creative.get(reverse("api:leads")).data[0]
        sent = creative.post(reverse("api:lead_send_quote", args=[lead["id"]]),
                             {"title": "Wedding day coverage", "amount": "3200", "deposit_pct": "25"})
        self.assertEqual(sent.status_code, 201)
        self.assertEqual(sent.data["status"], "sent")
        # total includes 10% GST (3200 -> 3520), deposit is 25% of that.
        self.assertEqual(sent.data["total"], "3520.00")
        self.assertEqual(sent.data["deposit_amount"], "880.00")

    def test_send_quote_rejects_bad_amount(self):
        creative = self._auth("harper@lens.test")
        lead = creative.get(reverse("api:leads")).data[0]
        self.assertEqual(
            creative.post(reverse("api:lead_send_quote", args=[lead["id"]]), {"amount": "0"}).status_code, 400)

    def test_client_cannot_send_quote(self):
        creative = self._auth("harper@lens.test")
        lead_id = creative.get(reverse("api:leads")).data[0]["id"]
        client = self._auth("olivia@lens.test")
        self.assertEqual(
            client.post(reverse("api:lead_send_quote", args=[lead_id]), {"amount": "100"}).status_code, 403)

    def test_viewer_role_and_creative_deliver(self):
        creative = self._auth("harper@lens.test")
        # a confirmed booking for this creative the client hasn't been delivered yet
        bookings = creative.get(reverse("api:bookings")).data
        target = next((b for b in bookings if b["status"] in (
            "confirmed", "planning", "shoot_completed", "editing")), None)
        if not target:
            self.skipTest("no deliverable booking in seed for harper")
        bid = target["id"]
        # creative sees viewer_is_client False and no client next_action
        detail = creative.get(reverse("api:booking_detail", args=[bid])).data
        self.assertFalse(detail["viewer_is_client"])
        self.assertIsNone(detail["next_action"])
        # deliver a gallery link
        resp = creative.post(reverse("api:booking_deliver", args=[bid]),
                             {"title": "Final gallery", "url": "https://drive.google.com/xyz"})
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.data["galleries"]), 1)

    def test_client_cannot_deliver(self):
        client = self._auth("olivia@lens.test")
        bid = client.get(reverse("api:bookings")).data[0]["id"]
        self.assertEqual(
            client.post(reverse("api:booking_deliver", args=[bid]),
                        {"url": "https://drive.google.com/x"}).status_code, 403)


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

    def test_booking_detail_includes_key_dates(self):
        """Shoot + deadlines mirror the web calendar; personal/blocked holds are
        excluded. icon/category match the dashboard feed for a consistent UI."""
        from django.utils import timezone
        from datetime import timedelta
        from apps.bookings.models import CalendarEvent as CE
        CE.objects.create(workspace=self.ws, booking=self.booking, event_type=CE.Type.SHOOT,
                          title="The shoot", start=timezone.now() + timedelta(days=10))
        CE.objects.create(workspace=self.ws, booking=self.booking, event_type=CE.Type.EDITING_DUE,
                          title="Edit due", start=timezone.now() - timedelta(days=1))
        # a personal hold on the same workspace must NOT leak into a booking's key dates
        CE.objects.create(workspace=self.ws, event_type=CE.Type.CUSTOM,
                          title="Holiday", start=timezone.now())

        kd = self.api.get(reverse("api:booking_detail", args=[str(self.booking.id)])).data["key_dates"]
        self.assertEqual(len(kd), 2)
        shoot = next(k for k in kd if k["category"] == "shoot")
        self.assertEqual(shoot["icon"], "📷")
        self.assertFalse(shoot["overdue"])
        editing = next(k for k in kd if k["type"] == "editing_due")
        self.assertEqual(editing["category"], "task")
        self.assertTrue(editing["overdue"])


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


class ApiCollaborationTests(TestCase):
    """The collaboration API must give the invited creative (B) the logistics
    and let them accept/decline — without ever leaking the client's identity."""

    def setUp(self):
        from decimal import Decimal
        from apps.bookings import services as flow
        from apps.bookings.models import BookingCollaborator
        from apps.contracts.models import ContractTemplate
        from apps.profiles.models import CreativeProfile, Package, Service
        User = get_user_model()
        self.flow = flow
        self.BC = BookingCollaborator

        a = User.objects.create_user(email="a@t.com", password="lens12345")
        self.a_ws = Workspace.objects.create(owner=a, business_name="Studio A", is_published=True)
        CreativeProfile.objects.create(workspace=self.a_ws, primary_category="events")
        customer = User.objects.create_user(email="hidden-client@example.com", password="x",
                                             first_name="Priya")
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        svc = Service.objects.create(workspace=self.a_ws, category="events", title="E")
        pkg = Package.objects.create(service=svc, name="Day", base_price=Decimal("3000"))
        e = flow.create_enquiry(client=customer, workspace=self.a_ws, event_type="events",
                                message="hi", location="Fitzroy")
        q = flow.send_quote(enquiry=e, title="Wedding coverage", package=pkg,
                            line_items=[{"label": "x", "amount": 3000}])
        self.booking = flow.accept_quote(q)
        self.booking.location = "Fitzroy"; self.booking.save()

        User.objects.create_user(email="b@t.com", password="lens12345")
        self.b_ws = Workspace.objects.create(
            owner=get_user_model().objects.get(email="b@t.com"), business_name="Studio B", is_published=True)
        CreativeProfile.objects.create(workspace=self.b_ws, primary_category="events")
        self.collab = flow.invite_collaborator(self.booking, self.b_ws, role="Second shooter",
                                               fee=Decimal("500"), by=a)

    def _auth(self, email):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {c.post(reverse('api:login'), {'email': email, 'password': 'lens12345'}).data['token']}")
        return c

    def test_pending_invite_listed_then_accept(self):
        c = self._auth("b@t.com")
        data = c.get(reverse("api:collaborations")).data
        self.assertEqual(len(data["pending"]), 1)
        self.assertEqual(len(data["active"]), 0)
        self.assertEqual(data["pending"][0]["booking"]["booked_by"], "Studio A")
        # accept
        r = c.post(reverse("api:collaboration_respond", args=[self.collab.id]), {"accept": True})
        self.assertEqual(r.status_code, 200)
        self.collab.refresh_from_db()
        self.assertEqual(self.collab.status, self.BC.Status.ACCEPTED)

    def test_payload_never_leaks_client_identity(self):
        import json
        c = self._auth("b@t.com")
        self.collab.status = self.BC.Status.ACCEPTED; self.collab.save()
        blob = json.dumps(c.get(reverse("api:collaboration_detail", args=[self.collab.id])).data)
        self.assertIn("Fitzroy", blob)            # logistics present
        self.assertIn("Studio A", blob)           # who hired them
        self.assertNotIn("hidden-client@example.com", blob)
        self.assertNotIn("Priya", blob)
        self.assertNotIn("client", blob.lower().replace("collaboration", ""))  # no client field

    def test_detail_gated_on_accept_and_owner(self):
        # pending -> detail 404 (must accept first)
        b = self._auth("b@t.com")
        self.assertEqual(b.get(reverse("api:collaboration_detail", args=[self.collab.id])).status_code, 404)
        # a different creative can't see it
        a = self._auth("a@t.com")
        self.assertEqual(a.get(reverse("api:collaboration_detail", args=[self.collab.id])).status_code, 404)

    def test_a_side_invite_list_pay_remove(self):
        from apps.bookings.models import BookingCollaborator
        # remove the auto-created invite from setUp so we start clean
        BookingCollaborator.objects.all().delete()
        a = self._auth("a@t.com")
        bid = str(self.booking.id)
        # invite by creative slug
        r = a.post(reverse("api:booking_collaborators", args=[bid]),
                   {"creative": self.b_ws.slug, "role": "Second shooter", "fee": "400"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data), 1)
        self.assertEqual(r.data[0]["workspace_name"], "Studio B")
        cid = r.data[0]["id"]
        # B accepts, then A pays
        c = BookingCollaborator.objects.get(pk=cid)
        c.status = BookingCollaborator.Status.ACCEPTED; c.save()
        pay = a.post(reverse("api:booking_collaborator_pay", args=[bid, cid]))
        self.assertEqual(pay.status_code, 200)
        self.assertTrue(pay.data["is_paid"])
        # remove
        rm = a.post(reverse("api:booking_collaborator_remove", args=[bid, cid]))
        self.assertEqual(rm.status_code, 200)
        self.assertEqual(a.get(reverse("api:booking_collaborators", args=[bid])).data, [])

    def test_a_side_requires_booking_owner(self):
        from apps.bookings.models import BookingCollaborator
        BookingCollaborator.objects.all().delete()
        # B is not the owner of A's booking -> 404
        b = self._auth("b@t.com")
        self.assertEqual(
            b.post(reverse("api:booking_collaborators", args=[str(self.booking.id)]),
                   {"creative": self.b_ws.slug}).status_code, 404)


class SecurityRegressionTests(TestCase):
    """Regression coverage for the security audit fixes (F8 PII leak, F9 state guard)."""

    def setUp(self):
        from decimal import Decimal
        from apps.bookings import services as flow
        from apps.contracts.models import ContractTemplate
        from apps.profiles.models import CreativeProfile, Package, Service
        from apps.reviews.models import Review
        User = get_user_model()
        self.creative = User.objects.create_user(email="cr@t.com", password="lens12345")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="Studio",
                                           is_published=True, slug="studio")
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")
        # a reviewer with NO display name — would previously fall back to email
        self.nameless = User.objects.create_user(email="harvest-me@example.com", password="lens12345")
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        svc = Service.objects.create(workspace=self.ws, category="events", title="E")
        pkg = Package.objects.create(service=svc, name="Day", base_price=Decimal("1000"))
        e = flow.create_enquiry(client=self.nameless, workspace=self.ws, event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", package=pkg, line_items=[{"label": "x", "amount": 1000}])
        self.booking = flow.accept_quote(q)
        Review.objects.create(booking=self.booking, client=self.nameless, workspace=self.ws,
                              rating=5, title="Great", body="loved it", verified=True)

    def test_public_creative_detail_does_not_leak_reviewer_email(self):
        import json
        r = APIClient().get(reverse("api:creative_detail", args=[self.ws.slug]))  # AllowAny
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("harvest-me@example.com", json.dumps(r.data))
        self.assertTrue(any(rev["client_name"] == "Verified client" for rev in r.data["reviews"]))

    def test_advance_blocked_on_unconfirmed_booking(self):
        c = APIClient()
        token = c.post(reverse("api:login"), {"email": "cr@t.com", "password": "lens12345"}).data["token"]
        c.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        # booking was just quote-accepted — not confirmed (no deposit paid)
        r = c.post(reverse("api:booking_advance", args=[str(self.booking.id)]), {"step": "shoot_completed"})
        self.assertEqual(r.status_code, 400)
        self.booking.refresh_from_db()
        self.assertNotEqual(self.booking.status, Booking.Status.SHOOT_COMPLETED)
