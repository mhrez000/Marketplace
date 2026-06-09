from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.utils import timezone

from apps.bookings import services as flow
from apps.contracts.models import ContractTemplate
from apps.enquiries.models import Quote
from apps.enquiries.services import expire_quotes
from apps.payments.models import Invoice
from apps.payments.services import mark_overdue_invoices, payment_reminders
from apps.profiles.models import CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class LifecycleHousekeepingTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw", first_name="C", last_name="L")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def _quote(self):
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws,
                                event_type="events", message="hi")
        return flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 500}])

    def test_quote_expires(self):
        q = self._quote()
        q.expires_at = timezone.now().date() - timedelta(days=1)
        q.save(update_fields=["expires_at"])
        self.assertTrue(q.is_expired)
        self.assertEqual(expire_quotes(), 1)
        q.refresh_from_db()
        self.assertEqual(q.status, Quote.Status.EXPIRED)

    def test_expired_quote_cannot_be_accepted(self):
        q = self._quote()
        q.expires_at = timezone.now().date() - timedelta(days=1)
        q.save(update_fields=["expires_at"])
        self.client.force_login(self.client_user)
        self.client.post(f"/portal/quote/{q.pk}/accept/", SERVER_NAME="localhost")
        q.refresh_from_db()
        self.assertNotEqual(q.status, Quote.Status.ACCEPTED)
        self.assertFalse(q.bookings.exists())

    def test_invoice_marked_overdue(self):
        q = self._quote()
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="C L")
        inv = b.invoices.get(invoice_type=Invoice.Type.DEPOSIT)
        inv.due_date = timezone.now().date() - timedelta(days=2)
        inv.save(update_fields=["due_date"])
        self.assertTrue(inv.is_overdue)
        self.assertEqual(mark_overdue_invoices(), 1)
        inv.refresh_from_db()
        self.assertEqual(inv.status, Invoice.Status.OVERDUE)

    def test_payment_reminder_emails_and_throttles(self):
        q = self._quote()
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="C L")
        inv = b.invoices.get(invoice_type=Invoice.Type.DEPOSIT)
        inv.due_date = timezone.now().date() - timedelta(days=1)
        inv.save(update_fields=["due_date"])
        mail.outbox = []
        self.assertEqual(payment_reminders(), 1)
        self.assertTrue(any("overdue" in m.subject.lower() for m in mail.outbox))
        # Throttled on immediate re-run.
        self.assertEqual(payment_reminders(), 0)

    def test_email_sent_on_quote(self):
        mail.outbox = []
        self._quote()
        # creative gets the enquiry email, client gets the quote email
        self.assertGreaterEqual(len(mail.outbox), 2)
