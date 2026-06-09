from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.bookings import services as flow
from apps.contracts.models import ContractTemplate
from apps.dashboard.analytics import workspace_analytics
from apps.profiles.models import CreativeProfile, Package, Service
from apps.workspaces.models import Workspace

User = get_user_model()


class AnalyticsTests(TestCase):
    def setUp(self):
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        self.creative = User.objects.create_user(email="c@t.com", password="x")
        self.client_user = User.objects.create_user(email="cl@t.com", password="pw")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events", view_count=100)
        svc = Service.objects.create(workspace=self.ws, category="events", title="E")
        self.pkg = Package.objects.create(service=svc, name="P", base_price=Decimal("1000"))

    def test_funnel_and_revenue(self):
        e = flow.create_enquiry(client=self.client_user, workspace=self.ws, event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", package=self.pkg, line_items=[{"label": "x", "amount": 1000}])
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name="cl")
        flow.pay_deposit(b)  # paid the deposit

        a = workspace_analytics(self.ws)
        labels = {f["label"]: f["value"] for f in a["funnel"]}
        self.assertEqual(labels["Enquiries"], 1)
        self.assertEqual(labels["Quotes sent"], 1)
        self.assertEqual(labels["Bookings"], 1)
        self.assertEqual(labels["Confirmed"], 1)
        self.assertEqual(a["paid"], b.deposit_amount)        # deposit recorded as revenue
        self.assertGreater(a["pipeline"], 0)                  # confirmed-but-not-complete
        self.assertEqual(a["profile_views"], 100)
        self.assertEqual(a["popular"][0].n, 1)                # the package was quoted once
        self.assertEqual(len(a["trend"]), 6)

    def test_analytics_page_renders(self):
        self.client.force_login(self.creative)
        r = self.client.get("/app/analytics/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Conversion funnel")
