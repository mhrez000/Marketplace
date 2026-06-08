from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.enquiries.models import Quote
from apps.payments.models import Payment
from apps.profiles.models import CreativeProfile, Package, Service
from apps.workspaces.models import Workspace

User = get_user_model()


class SpineTestCase(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@test.com", password="x")
        self.client_user = User.objects.create_user(email="cl@test.com", password="x", first_name="Cl", last_name="Ient")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="Test Studio", is_published=True)
        self.ws.mark_verified()
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")
        svc = Service.objects.create(workspace=self.ws, category="events", title="Events")
        self.pkg = Package.objects.create(service=svc, name="Pkg", base_price=Decimal("1000"))

    def _quote(self):
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws,
                                event_type="events", message="hi")
        return flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 1000}])

    def test_gst_and_deposit_maths(self):
        q = self._quote()
        self.assertEqual(q.subtotal, Decimal("1000"))
        self.assertEqual(q.gst, Decimal("100.00"))      # 10% AU GST
        self.assertEqual(q.total, Decimal("1100"))
        self.assertEqual(q.deposit_amount, Decimal("275.00"))  # 25% of total

    def test_full_lifecycle(self):
        q = self._quote()
        b = flow.accept_quote(q)
        self.assertEqual(b.status, Booking.Status.CONTRACT_SENT)
        flow.sign_contract_client(b.contract, name="Cl Ient")
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONTRACT_SIGNED)
        flow.pay_deposit(b)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
        # A successful payment with a computed platform fee exists.
        p = Payment.objects.get(invoice__booking=b)
        self.assertEqual(p.status, Payment.Status.SUCCEEDED)
        self.assertEqual(p.platform_fee, (p.amount * Decimal("0.015")).quantize(Decimal("0.01")))

    def test_illegal_transition_blocked(self):
        q = self._quote()
        b = flow.accept_quote(q)
        # Cannot jump straight from contract_sent to completed.
        self.assertFalse(b.transition(Booking.Status.COMPLETED))
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONTRACT_SENT)

    def test_deposit_not_double_charged(self):
        q = self._quote()
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="Cl Ient")
        flow.pay_deposit(b)
        flow.pay_deposit(b)  # idempotent-ish: invoice already paid
        self.assertEqual(Payment.objects.filter(invoice__booking=b).count(), 1)


class PortalSecurityTestCase(TestCase):
    """A client must never see another client's booking."""

    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        creative = User.objects.create_user(email="c2@test.com", password="x")
        self.owner_client = User.objects.create_user(email="owner@test.com", password="pw")
        self.other_client = User.objects.create_user(email="other@test.com", password="pw")
        ws = Workspace.objects.create(owner=creative, business_name="S2", is_published=True)
        e = flow.create_enquiry(client=self.owner_client, workspace=ws, event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 500}])
        self.booking = flow.accept_quote(q)

    def test_other_client_cannot_view_booking(self):
        self.client.force_login(self.other_client)
        r = self.client.get(f"/portal/booking/{self.booking.pk}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 404)

    def test_owner_client_can_view_booking(self):
        self.client.force_login(self.owner_client)
        r = self.client.get(f"/portal/booking/{self.booking.pk}/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
