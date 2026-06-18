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
