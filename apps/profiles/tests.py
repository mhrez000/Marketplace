from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.bookings import services as flow
from apps.contracts.models import ContractTemplate
from apps.profiles import services as availability
from apps.profiles.models import Availability, CreativeProfile
from apps.workspaces.models import Workspace

User = get_user_model()


class AvailabilityTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.c1 = User.objects.create_user(email="a@t.com", password="x", first_name="A", last_name="One")
        self.c2 = User.objects.create_user(email="b@t.com", password="x", first_name="B", last_name="Two")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")
        self.date = timezone.now().date() + timedelta(days=20)

    def _booking(self, client):
        e = flow.create_enquiry(client=client, workspace=self.ws, event_type="events",
                                message="hi", event_date=self.date)
        q = flow.send_quote(enquiry=e, title="Q", line_items=[{"label": "x", "amount": 500}])
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name=client.get_full_name())
        return b

    def test_confirm_marks_date_booked(self):
        b = self._booking(self.c1)
        flow.pay_deposit(b)
        self.assertFalse(availability.is_available(self.ws, self.date))
        self.assertTrue(Availability.objects.filter(
            workspace=self.ws, date=self.date, status="booked").exists())

    def test_double_booking_blocked(self):
        flow.pay_deposit(self._booking(self.c1))
        b2 = self._booking(self.c2)
        with self.assertRaises(flow.DateUnavailable):
            flow.pay_deposit(b2)

    def test_cancel_frees_date(self):
        b1 = self._booking(self.c1)
        flow.pay_deposit(b1)
        flow.cancel_booking(b1, by="client")
        self.assertTrue(availability.is_available(self.ws, self.date))
        # Now a second client can book the freed date.
        b2 = self._booking(self.c2)
        flow.pay_deposit(b2)
        self.assertTrue(b2.is_confirmed)

    def test_manual_block_prevents_booking(self):
        availability.block(self.ws, self.date)
        self.assertFalse(availability.is_available(self.ws, self.date))
        b = self._booking(self.c1)
        with self.assertRaises(flow.DateUnavailable):
            flow.pay_deposit(b)

    def test_search_excludes_busy_workspace(self):
        flow.pay_deposit(self._booking(self.c1))
        busy = availability.unavailable_workspace_ids(self.date)
        self.assertIn(self.ws.id, busy)
