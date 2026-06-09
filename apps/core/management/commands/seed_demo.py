"""Seed a full, clickable demo: test accounts + a complete booking lifecycle.

Run:  python manage.py seed_demo
All accounts use password:  lens12345

Re-running wipes prior @lens.test demo data and rebuilds it.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.bookings import services as flow
from apps.bookings.models import Booking
from apps.contracts.models import ContractTemplate
from apps.galleries.models import Asset, Gallery
from apps.payments.models import Subscription
from apps.profiles.models import (Availability, CreativeProfile, Package, Service,
                                  VerificationDocument)
from apps.workspaces.models import Member, Workspace

User = get_user_model()
PASSWORD = "lens12345"


class Command(BaseCommand):
    help = "Seed demo data (test accounts + full booking lifecycle)."

    @transaction.atomic
    def handle(self, *args, **opts):
        self.stdout.write("Wiping prior demo data (@lens.test)…")
        User.objects.filter(email__endswith="@lens.test").delete()

        self._contract_templates()

        admin = self._user("admin@lens.test", "Platform", "Admin", staff=True, superuser=True)

        # ── Creatives ──────────────────────────────────────────────────────
        harper = self._creative(
            "harper@lens.test", "Harper", "Lee", "Harper Studio", "weddings", "navy",
            headline="Candid, film-inspired wedding photography",
            bio="We shoot weddings the way you'll actually remember them — warm, candid and "
                "unposed. Based in Fitzroy, available across Victoria.",
            suburb="Fitzroy", styles="Candid, Film, Documentary, Romantic",
            equipment="Sony A7IV, prime lenses, film bodies", starting_price=2400,
            featured=True, packages=[
                ("Elopement", 2400, "Up to 4 hours", "4 hours coverage\n200+ edited photos\nOnline gallery"),
                ("Half Day", 3200, "6 hours", "6 hours coverage\n400+ edited photos\nOnline gallery\nSneak peeks"),
                ("Full Day", 4800, "10 hours", "10 hours coverage\n800+ edited photos\n2 photographers\nWedding album"),
            ])
        marlow = self._creative(
            "marlow@lens.test", "Marlow", "Reed", "Marlow Films", "business", "teal",
            headline="Cinematic brand films & social reels",
            bio="Brand films and short-form content that actually convert. Trusted by Melbourne "
                "cafes, gyms and personal brands.",
            suburb="Richmond", styles="Cinematic, Brand, Reels, Product", starting_price=1800,
            featured=True, packages=[
                ("Reel Pack", 1800, "3 reels", "Half-day shoot\n3 edited reels\nLicensed music"),
                ("Brand Film", 3500, "1–2 min film", "Full-day shoot\n1 hero film\n3 cutdowns\nColour grade"),
            ])
        bright = self._creative(
            "bright@lens.test", "Bri", "Tan", "Bright & Co.", "real-estate", "sky",
            headline="Next-day real estate photography & drone",
            bio="Fast-turnaround property photography, drone and floor plans for agents who need "
                "it live tomorrow.",
            suburb="Brunswick", styles="Real Estate, Drone, Twilight, Floorplans", starting_price=320,
            packages=[
                ("Essential", 320, "Up to 15 photos", "15 HDR photos\nNext-day delivery"),
                ("Premium", 540, "Photos + drone", "25 HDR photos\nDrone aerials\nFloor plan\nTwilight shot"),
            ])
        juniper = self._creative(
            "juniper@lens.test", "June", "Park", "Juniper Lane", "family", "navy",
            headline="Warm family & newborn portraits",
            bio="Relaxed, joyful family sessions in natural light. Newborns, milestones and "
                "extended family.",
            suburb="St Kilda", styles="Family, Newborn, Lifestyle, Natural light", starting_price=450,
            packages=[("Mini Session", 450, "30 min", "30 min session\n15 edited photos"),
                      ("Full Session", 750, "90 min", "90 min session\n50 edited photos\nPrint credit")])

        # A pending creative (unverified) to show the admin approval queue.
        self._creative(
            "pending@lens.test", "Noa", "West", "Newport Films", "events", "teal",
            headline="Event coverage across Melbourne", bio="New to the platform — pending review.",
            suburb="Newport", styles="Events, Parties", starting_price=600,
            verified=False, published=False, packages=[("Event Hour", 600, "Per hour", "Hourly event coverage")])

        # ── Clients ────────────────────────────────────────────────────────
        olivia = self._user("olivia@lens.test", "Olivia", "Bennett")
        sam = self._user("sam@lens.test", "Sam", "Okafor")
        northcote = self._user("northcote@lens.test", "Northcote", "Realty")

        # The admin account also owns a studio, so logging in as admin@lens.test
        # shows a fully-populated creative dashboard (not just the empty state).
        admin_ws = self._build_workspace(
            admin, "Aperture Collective", "weddings", "teal",
            headline="Editorial weddings & events", suburb="Carlton",
            bio="The platform demo studio — explore a full pipeline here.",
            styles="Editorial, Candid, Documentary", starting_price=2800, featured=False,
            packages=[("Half Day", 2800, "6 hours", "6 hours\n400+ photos\nGallery"),
                      ("Full Day", 4200, "10 hours", "10 hours\n800+ photos\n2 shooters")])

        # ── Flows ──────────────────────────────────────────────────────────
        today = timezone.now().date()

        # Populate the admin studio: a completed job, a confirmed booking,
        # a quote out, and a fresh lead to action.
        self._completed_booking(olivia, admin_ws, event_date=today - timedelta(days=15),
                                rating=5, review_body="The Aperture team were a dream to work with!")
        self._confirmed_booking(sam, admin_ws, event_date=today + timedelta(days=25))
        e_admin = flow.create_enquiry(client=northcote, workspace=admin_ws, event_type="events",
                                      message="Corporate end-of-year party — 4 hours coverage?",
                                      event_date=today + timedelta(days=40), location="Carlton VIC",
                                      budget_band="$2,000–$3,000")
        flow.send_quote(enquiry=e_admin, title="Events half-day",
                        line_items=[{"label": "4 hours event coverage", "amount": 2200}])
        flow.create_enquiry(client=sam, workspace=admin_ws, event_type="weddings",
                            message="Hi! Checking availability for an autumn wedding in the Dandenongs.",
                            event_date=today + timedelta(days=120), location="Olinda VIC",
                            budget_band="$3k–$4k")
        # Shot last week, now mid-edit -> live delivery deadlines (overdue + due-soon).
        self._production_booking(olivia, admin_ws, event_date=today - timedelta(days=6))
        self._production_booking(sam, harper, event_date=today - timedelta(days=3))

        # 1) Completed lifecycle: Olivia ↔ Harper (shows revenue, gallery, review)
        self._completed_booking(olivia, harper, event_date=today - timedelta(days=20))

        # 2) Mid-flow confirmed booking: Sam ↔ Marlow (deposit paid, awaiting delivery)
        self._confirmed_booking(sam, marlow, event_date=today + timedelta(days=18))

        # 3) Quote awaiting acceptance: Northcote ↔ Bright (client can accept)
        e3 = flow.create_enquiry(client=northcote, workspace=bright, event_type="real-estate",
                                 message="Need photos + drone for a Richmond listing next week.",
                                 event_date=today + timedelta(days=6), location="Richmond VIC",
                                 budget_band="$500–$600")
        flow.send_quote(enquiry=e3, title="Premium real estate package",
                        line_items=[{"label": "25 HDR photos + drone", "amount": 540}])

        # 4) Brand-new enquiry: Olivia ↔ Juniper (creative needs to quote)
        flow.create_enquiry(client=olivia, workspace=juniper, event_type="family",
                            message="Looking for a spring family session for 5 in St Kilda.",
                            event_date=today + timedelta(days=30), location="St Kilda VIC",
                            budget_band="$700ish")

        # A couple of extra reviews so ratings populate.
        self._completed_booking(sam, harper, event_date=today - timedelta(days=60),
                                rating=5, review_body="Absolutely stunning photos, so easy to work with!")
        self._completed_booking(northcote, marlow, event_date=today - timedelta(days=45),
                                rating=4, review_body="Great brand film, quick turnaround.")

        self._print_summary()

    # ── helpers ────────────────────────────────────────────────────────────
    def _user(self, email, first, last, staff=False, superuser=False):
        u = User(email=email, username=email, first_name=first, last_name=last,
                 is_staff=staff, is_superuser=superuser,
                 role_type="admin" if superuser else "client")
        u.set_password(PASSWORD)
        u.save()
        return u

    def _creative(self, email, first, last, business, category, accent, *, headline, bio,
                  suburb, styles, starting_price, equipment="", packages=None,
                  featured=False, verified=True, published=True):
        user = self._user(email, first, last)
        user.role_type = "creative"
        user.save(update_fields=["role_type"])
        return self._build_workspace(
            user, business, category, accent, headline=headline, bio=bio, suburb=suburb,
            styles=styles, starting_price=starting_price, equipment=equipment,
            packages=packages, featured=featured, verified=verified, published=published)

    def _build_workspace(self, user, business, category, accent, *, headline, bio,
                         suburb, styles, starting_price, equipment="", packages=None,
                         featured=False, verified=True, published=True):
        ws = Workspace.objects.create(owner=user, type=Workspace.Type.SOLO,
                                      business_name=business, abn="12 345 678 901",
                                      is_published=published)
        if verified:
            ws.mark_verified()
        Member.objects.create(workspace=ws, user=user, role=Member.Role.OWNER)
        Subscription.objects.create(workspace=ws, plan=Subscription.Plan.PRO,
                                    period_end=timezone.now().date() + timedelta(days=300))

        CreativeProfile.objects.create(
            workspace=ws, headline=headline, bio=bio, suburb=suburb, city="Melbourne",
            state="VIC", primary_category=category, styles=styles, equipment=equipment,
            starting_price=Decimal(str(starting_price)), accent=accent, is_featured=featured,
            response_time_hours=12 if featured else 24)

        service = Service.objects.create(workspace=ws, category=category,
                                         title=f"{business} — {category.replace('-', ' ').title()}")
        for name, price, desc, inclusions in (packages or []):
            Package.objects.create(service=service, name=name, base_price=Decimal(str(price)),
                                   description=desc, inclusions=inclusions)

        # Verification docs (approved for verified creatives, pending otherwise).
        status = (VerificationDocument.Status.APPROVED if verified
                  else VerificationDocument.Status.PENDING)
        for dt in (VerificationDocument.DocType.ABN, VerificationDocument.DocType.INSURANCE,
                   VerificationDocument.DocType.WWCC):
            VerificationDocument.objects.create(workspace=ws, doc_type=dt, status=status,
                                                reference=f"{dt}-{ws.pk}")

        # Some availability.
        for i in range(1, 40, 3):
            Availability.objects.get_or_create(
                workspace=ws, date=timezone.now().date() + timedelta(days=i),
                defaults={"status": Availability.Status.AVAILABLE})
        return ws

    def _quote_for(self, ws):
        pkg = Package.objects.filter(service__workspace=ws).order_by("-base_price").first()
        amount = float(pkg.base_price) if pkg else 2000.0
        return pkg, [{"label": pkg.name if pkg else "Coverage", "amount": amount}]

    def _confirmed_booking(self, client, ws, *, event_date):
        e = flow.create_enquiry(client=client, workspace=ws, event_type=ws.profile.primary_category,
                                message="Hi! Keen to book — are you available?",
                                event_date=event_date, location=f"{ws.profile.suburb} VIC")
        pkg, items = self._quote_for(ws)
        q = flow.send_quote(enquiry=e, title=f"{pkg.name if pkg else 'Custom'} package",
                            line_items=items, package=pkg)
        b = flow.accept_quote(q)
        flow.sign_contract_client(b.contract, name=client.get_full_name())
        flow.sign_contract_creative(b.contract, name=ws.business_name)
        flow.pay_deposit(b)
        return b

    def _production_booking(self, client, ws, *, event_date):
        """Confirmed + shot, now mid-edit — populates the Deliveries tab with
        real overdue/due-soon milestones (event_date should be a few days ago)."""
        b = self._confirmed_booking(client, ws, event_date=event_date)
        b.transition(Booking.Status.SHOOT_COMPLETED, force=True)
        b.transition(Booking.Status.EDITING, force=True)
        return b

    def _completed_booking(self, client, ws, *, event_date, rating=5,
                           review_body="Incredible work — exceeded our expectations!"):
        b = self._confirmed_booking(client, ws, event_date=event_date)
        b.transition(Booking.Status.SHOOT_COMPLETED, force=True)
        b.transition(Booking.Status.EDITING, force=True)
        g = Gallery.objects.create(booking=b, title=f"{b.title} — Gallery",
                                   gallery_type=Gallery.Type.PHOTO)
        accents = ["navy", "teal", "sky"]
        for i in range(12):
            Asset.objects.create(gallery=g, title=f"Image {i+1}", accent=accents[i % 3],
                                 is_favourite=(i < 2))
        flow.deliver_gallery(g)
        flow.pay_final(b)
        flow.create_review(booking=b, rating=rating, title="Highly recommend", body=review_body)
        return b

    def _contract_templates(self):
        if ContractTemplate.objects.exists():
            return
        for name, ctype in [("Wedding agreement", "wedding"), ("Events agreement", "events"),
                            ("Real estate agreement", "real_estate"),
                            ("Commercial agreement", "commercial")]:
            ContractTemplate.objects.create(name=name, contract_type=ctype, body=flow.DEFAULT_CONTRACT)

    def _print_summary(self):
        line = "=" * 58
        self.stdout.write(self.style.SUCCESS(f"\n{line}\n  DEMO SEEDED — all passwords: {PASSWORD}\n{line}"))
        rows = [
            ("ADMIN (owns a studio + /admin/)", "admin@lens.test"),
            ("Creative - Harper Studio (weddings)", "harper@lens.test"),
            ("Creative - Marlow Films (brand/reels)", "marlow@lens.test"),
            ("Creative - Bright & Co. (real estate)", "bright@lens.test"),
            ("Creative - Juniper Lane (family)", "juniper@lens.test"),
            ("Creative - Newport Films (PENDING approval)", "pending@lens.test"),
            ("Client - Olivia Bennett", "olivia@lens.test"),
            ("Client - Sam Okafor", "sam@lens.test"),
            ("Client - Northcote Realty", "northcote@lens.test"),
        ]
        for label, email in rows:
            self.stdout.write(f"  {label:<46} {email}")
        self.stdout.write(line)
        self.stdout.write("  Try: log in as harper@lens.test -> Leads -> send a quote.")
        self.stdout.write("       northcote@lens.test -> My portal -> accept quote -> sign -> pay.")
        self.stdout.write(line)
