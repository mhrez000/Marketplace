from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.profiles.models import CreativeProfile
from apps.reviews.services import review_reminders
from apps.workspaces.models import Workspace

User = get_user_model()


class ReviewReminderTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def _complete(self):
        from django.utils import timezone
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws,
                                event_type="events", message="hi",
                                event_date=timezone.now().date() - timedelta(days=20))
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 500}])
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="C L")
        flow.pay_deposit(b)
        b.transition(Booking.Status.SHOOT_COMPLETED, force=True)
        b.transition(Booking.Status.EDITING, force=True)
        g = b.galleries.create(title="G")
        flow.deliver_gallery(g)
        flow.pay_final(b)
        return b

    def test_completed_booking_awaiting_review(self):
        b = self._complete()
        self.assertTrue(b.awaiting_review)

    def test_review_reminder_sent_and_throttled(self):
        self._complete()
        mail.outbox = []
        self.assertEqual(review_reminders(), 1)
        self.assertTrue(mail.outbox)
        self.assertEqual(review_reminders(), 0)  # throttled

    def test_reviewed_booking_not_reminded(self):
        b = self._complete()
        flow.create_review(booking=b, rating=5, body="great")
        b.refresh_from_db()
        self.assertFalse(b.awaiting_review)
        self.assertEqual(review_reminders(), 0)
