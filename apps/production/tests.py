from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.bookings import services as flow
from apps.contracts.models import ContractTemplate
from apps.production.services import generate_reminders
from apps.profiles.models import CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class DeliveryTrackerTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="wedding", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="x", first_name="Cl", last_name="Ient")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="Studio", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="weddings")

    def _confirm(self, *, days_ago=None, days_ahead=None):
        if days_ago is not None:
            event = timezone.now().date() - timedelta(days=days_ago)
        else:
            event = timezone.now().date() + timedelta(days=days_ahead or 30)
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws,
                                event_type="weddings", message="hi", event_date=event)
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 1000}])
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="Cl Ient")
        flow.pay_deposit(b)
        return b

    def test_deliverables_generated_on_confirm(self):
        b = self._confirm(days_ahead=30)
        kinds = set(b.deliverables.values_list("kind", flat=True))
        self.assertIn("final_delivery", kinds)
        self.assertIn("backup", kinds)
        # Wedding final delivery is ~6 weeks after the event.
        fd = b.deliverables.get(kind="final_delivery")
        self.assertEqual(fd.due_date, b.event_date + timedelta(days=42))

    def test_overdue_and_due_soon_flags(self):
        b = self._confirm(days_ago=6)  # shot last week
        backup = b.deliverables.get(kind="backup")   # due event+1 => 5 days ago
        self.assertTrue(backup.is_overdue)
        self.assertFalse(backup.is_done)
        cull = b.deliverables.get(kind="cull")        # due event+7 => tomorrow-ish
        self.assertTrue(cull.is_due_soon)

    def test_reminders_raised_and_throttled(self):
        self._confirm(days_ago=6)
        # Confirmation itself notifies; count only delivery reminders.
        first = generate_reminders(self.ws)
        self.assertGreater(first, 0)
        # Immediately re-running raises nothing (20h throttle).
        self.assertEqual(generate_reminders(self.ws), 0)

    def test_completed_booking_closes_checklist(self):
        b = self._confirm(days_ago=10)
        b.transition(b.Status.SHOOT_COMPLETED, force=True)
        b.transition(b.Status.EDITING, force=True)
        g = b.galleries.create(title="G")
        flow.deliver_gallery(g)
        self.assertTrue(b.deliverables.get(kind="final_delivery").is_done)
        flow.pay_final(b)
        self.assertTrue(all(d.is_done for d in b.deliverables.all()))
