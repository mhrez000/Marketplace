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


class OpsDashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(email="staff@t.com", password="x", is_staff=True)
        self.normal = User.objects.create_user(email="n@t.com", password="x")

    def test_staff_sees_ops(self):
        self.client.force_login(self.staff)
        r = self.client.get("/app/ops/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "GMV")
        self.assertContains(r, "Open disputes")

    def test_non_staff_404(self):
        self.client.force_login(self.normal)
        r = self.client.get("/app/ops/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 404)


class ChecklistAndDeliveriesTests(TestCase):
    def setUp(self):
        from apps.workspaces.models import Workspace
        from apps.profiles.models import CreativeProfile
        self.creative = User.objects.create_user(email="cr@t.com", password="x")
        self.ws = Workspace.objects.create(owner=self.creative, business_name="S", is_published=True)
        CreativeProfile.objects.create(workspace=self.ws, primary_category="events")

    def test_checklist_add_and_delete(self):
        self.client.force_login(self.creative)
        self.client.post("/app/checklist/", {"action": "add", "label": "Backup", "day_offset": "1"},
                         SERVER_NAME="localhost")
        self.assertEqual(self.ws.task_templates.count(), 1)
        t = self.ws.task_templates.first()
        self.client.post("/app/checklist/", {"action": "delete", "id": t.pk}, SERVER_NAME="localhost")
        self.assertEqual(self.ws.task_templates.count(), 0)

    def test_overview_hides_completeness_when_done(self):
        from django.utils import timezone

        from apps.profiles.models import Package, Service
        self.client.force_login(self.creative)
        # a fresh profile is incomplete -> the card shows
        self.assertContains(self.client.get("/app/", SERVER_NAME="localhost"), "Profile completeness")

        p = self.ws.profile
        p.headline = "Editorial"; p.bio = "We shoot weddings"; p.starting_price = 2000; p.save()
        svc = Service.objects.create(workspace=self.ws, category="events", title="E")
        Package.objects.create(service=svc, name="Day", base_price=2000)
        self.ws.verified_at = timezone.now(); self.ws.save()

        # now 100% complete -> the card (and its Edit profile button) is hidden
        r = self.client.get("/app/", SERVER_NAME="localhost")
        self.assertNotContains(r, "Edit profile")

    def test_search_finds_leads(self):
        from apps.bookings import services as flow
        from apps.contracts.models import ContractTemplate
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        client = User.objects.create_user(email="finder@t.com", password="x", first_name="Findable")
        flow.create_enquiry(client=client, workspace=self.ws, event_type="events", message="hi")

        self.client.force_login(self.creative)
        r = self.client.get("/app/search/", {"q": "Findable"}, SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "finder@t.com")
        # empty query just shows the prompt
        self.assertEqual(self.client.get("/app/search/", SERVER_NAME="localhost").status_code, 200)

    def test_package_add_edit_delete(self):
        from apps.profiles.models import Package
        self.client.force_login(self.creative)
        # add
        self.client.post("/app/profile/", {"action": "add_package", "name": "Half Day",
                                           "base_price": "3200", "inclusions": "6 hours\nGallery"},
                         SERVER_NAME="localhost")
        pkg = Package.objects.filter(service__workspace=self.ws).first()
        self.assertIsNotNone(pkg)
        self.assertEqual(str(pkg.base_price), "3200.00")
        # edit
        self.client.post("/app/profile/", {"action": "edit_package", "package_id": pkg.pk,
                                           "name": "Half Day", "base_price": "3500"},
                         SERVER_NAME="localhost")
        pkg.refresh_from_db()
        self.assertEqual(str(pkg.base_price), "3500.00")
        # add without a price is rejected
        self.client.post("/app/profile/", {"action": "add_package", "name": "Bad"},
                         SERVER_NAME="localhost")
        self.assertEqual(Package.objects.filter(service__workspace=self.ws).count(), 1)
        # delete
        self.client.post("/app/profile/", {"action": "delete_package", "package_id": pkg.pk},
                         SERVER_NAME="localhost")
        self.assertEqual(Package.objects.filter(service__workspace=self.ws).count(), 0)

    def test_deliveries_panel_partial(self):
        self.client.force_login(self.creative)
        r = self.client.get("/app/deliveries/?panel=1", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "<html")  # fragment for HTMX swap

    def test_deliveries_post_redirects(self):
        """Regression: every deliveries action builds its redirect with reverse();
        a missing import made every POST 500 with NameError."""
        from apps.contracts.models import ContractTemplate
        ContractTemplate.objects.create(name="Std", contract_type="events", body=flow.DEFAULT_CONTRACT)
        svc = Service.objects.create(workspace=self.ws, category="events", title="E")
        pkg = Package.objects.create(service=svc, name="P", base_price=Decimal("1000"))
        client_user = User.objects.create_user(email="cl2@t.com", password="pw")
        e = flow.create_enquiry(client=client_user, workspace=self.ws, event_type="events", message="hi")
        q = flow.send_quote(enquiry=e, title="Q", package=pkg, line_items=[{"label": "x", "amount": 1000}])
        booking = flow.accept_quote(q)

        self.client.force_login(self.creative)
        # add_task and apply_checklist both go through reverse() to redirect
        r = self.client.post("/app/deliveries/",
                             {"action": "add_task", "booking": str(booking.pk), "title": "Cull RAWs"},
                             SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(booking.deliverables.filter(title="Cull RAWs").count(), 1)
        r2 = self.client.post("/app/deliveries/",
                              {"action": "apply_checklist", "booking": str(booking.pk)},
                              SERVER_NAME="localhost")
        self.assertEqual(r2.status_code, 302)

    def test_calendar_events_feed_is_json(self):
        self.client.force_login(self.creative)
        r = self.client.get("/app/calendar/events/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["content-type"], "application/json")
        import json
        self.assertIsInstance(json.loads(r.content), list)

    def test_calendar_page_loads_fullcalendar(self):
        self.client.force_login(self.creative)
        r = self.client.get("/app/calendar/", SERVER_NAME="localhost")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "multiMonthYear")  # year/month/week/day views wired
