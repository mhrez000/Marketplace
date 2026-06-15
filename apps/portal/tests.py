from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.profiles.models import CreativeProfile, Package, Service
from apps.workspaces.models import Workspace

User = get_user_model()


class PortalSignFlowTests(TestCase):
    """The quote -> sign -> deposit chain the client drives from the portal."""

    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="cr@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")
        svc = Service.objects.create(workspace=self.ws, category="events", title="E")
        self.pkg = Package.objects.create(service=svc, name="P", base_price=Decimal("1000"))
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws, event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", package=self.pkg,
                            line_items=[{"label": "x", "amount": 1000}])
        self.booking = flow.accept_quote(q)

    def test_accept_leaves_booking_in_contract_sent(self):
        # The sign banner is gated on this status, so the invariant matters.
        self.assertEqual(self.booking.status, Booking.Status.CONTRACT_SENT)

    def test_sign_banner_shows_after_accepting_quote(self):
        """Regression: the banner was gated on QUOTE_ACCEPTED, a state the booking
        is never persisted in, so clients could never sign."""
        self.client.force_login(self.client_user)
        r = self.client.get(f"/portal/booking/{self.booking.pk}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "sign your contract")
        self.assertContains(r, "signature_name")

    def test_signing_advances_to_pay_deposit(self):
        self.client.force_login(self.client_user)
        r = self.client.post(f"/portal/booking/{self.booking.pk}/",
                             {"action": "sign_contract", "signature_name": "Client Name"},
                             SERVER_NAME="localhost", follow=True)
        self.assertEqual(r.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONTRACT_SIGNED)
        self.assertContains(r, "pay your deposit")
