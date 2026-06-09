from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.galleries.models import Gallery
from apps.galleries.providers import detect_provider
from apps.profiles.models import CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class ProviderDetectionTests(TestCase):
    def test_known_providers(self):
        self.assertEqual(detect_provider("https://drive.google.com/drive/folders/x")["name"], "Google Drive")
        self.assertEqual(detect_provider("https://www.dropbox.com/sh/x")["name"], "Dropbox")
        self.assertEqual(detect_provider("https://jane.pixieset.com/wedding")["name"], "Pixieset")
        self.assertEqual(detect_provider("https://we.tl/t-abc")["name"], "WeTransfer")

    def test_unknown_and_empty(self):
        self.assertEqual(detect_provider("https://example.com/x")["name"], "External link")
        self.assertEqual(detect_provider("")["name"], "")


class LinkDeliveryTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")
        from django.utils import timezone
        from datetime import timedelta
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws, event_type="events",
                                message="hi", event_date=timezone.now().date() + timedelta(days=5))
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 500}])
        self.booking = flow.accept_quote(q)
        flow.sign_contract_client(self.booking.contract, name="cl")
        flow.pay_deposit(self.booking)  # -> confirmed

    def test_deliver_via_link_advances_booking(self):
        g = Gallery.objects.create(booking=self.booking, title="G",
                                   delivery_url="https://drive.google.com/drive/folders/abc")
        flow.deliver_gallery(g)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.DELIVERED)
        self.assertTrue(g.is_link_delivery)
        self.assertEqual(g.provider["name"], "Google Drive")

    def test_deliver_link_view_validates_url(self):
        self.client.force_login(self.creative)
        url = f"/app/bookings/{self.booking.pk}/"
        self.client.post(url, {"action": "deliver_link", "delivery_url": "not-a-url"}, SERVER_NAME="localhost")
        self.assertFalse(self.booking.galleries.exists())  # rejected
        self.client.post(url, {"action": "deliver_link", "delivery_url": "https://dropbox.com/sh/x"}, SERVER_NAME="localhost")
        self.assertTrue(self.booking.galleries.filter(delivery_url__gt="").exists())  # accepted
