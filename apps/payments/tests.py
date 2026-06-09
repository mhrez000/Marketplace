from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.payments.services import TestGateway, get_gateway
from apps.profiles.models import CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class GatewayTests(TestCase):
    def test_default_gateway_is_test(self):
        # No STRIPE_SECRET_KEY in test settings -> test gateway.
        self.assertIsInstance(get_gateway(), TestGateway)

    def test_webhook_inert_without_config(self):
        r = self.client.post("/api/v1/webhooks/stripe/", b"{}",
                             content_type="application/json", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 503)


class SettleInvoiceTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def test_deposit_settles_and_is_idempotent(self):
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws,
                                event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 400}])
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="cl")
        inv = b.invoices.get(invoice_type="deposit")
        flow.pay_deposit(b)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
        # Re-settling the same invoice doesn't double-advance.
        flow.settle_invoice(inv)
        b.refresh_from_db()
        self.assertEqual(b.status, Booking.Status.CONFIRMED)
