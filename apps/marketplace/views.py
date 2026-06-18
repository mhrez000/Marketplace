from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.bookings.services import create_enquiry
from apps.core.selectors import annotate_ratings
from apps.marketplace.models import Favourite
from apps.profiles.models import CATEGORY_CHOICES, CreativeProfile
from apps.workspaces.models import Workspace

CATEGORIES = [
    {"slug": "weddings", "name": "Weddings", "icon": "heart", "blurb": "Photographers & videographers for your day."},
    {"slug": "events", "name": "Events", "icon": "sparkles", "blurb": "Birthdays, engagements, corporate, parties."},
    {"slug": "real-estate", "name": "Real Estate", "icon": "home", "blurb": "Fast-turnaround property shoots & drone."},
    {"slug": "business", "name": "Business & Brand", "icon": "briefcase", "blurb": "Brand films, product, content & reels."},
    {"slug": "family", "name": "Family & Portrait", "icon": "users", "blurb": "Portraits, newborns, milestones."},
    {"slug": "content", "name": "Content & Reels", "icon": "video", "blurb": "Social content for creators & brands."},
]


def _published_profiles():
    from apps.profiles.services import filter_listable
    qs = CreativeProfile.objects.filter(workspace__is_published=True).select_related("workspace")
    return annotate_ratings(filter_listable(qs))


def home(request):
    featured = list(_published_profiles().order_by("-is_featured", "-avg_rating")[:4])
    return render(request, "marketplace/home.html", {"categories": CATEGORIES, "featured": featured})


def search(request):
    query = request.GET.get("q", "").strip()
    location = request.GET.get("location", "").strip()
    category = request.GET.get("category", "").strip()
    on_date = request.GET.get("date", "").strip()

    qs = _published_profiles()
    if category:
        qs = qs.filter(primary_category=category)
    if on_date:
        # Hide creatives who are blocked or already booked on the requested date.
        from apps.profiles.services import unavailable_workspace_ids
        busy = unavailable_workspace_ids(on_date)
        if busy:
            qs = qs.exclude(workspace_id__in=busy)
    if query:
        # Match a category label, or free-text across headline/bio/styles/business name.
        cat_match = next((c[0] for c in CATEGORY_CHOICES if c[1].lower() in query.lower()), None)
        cond = (Q(headline__icontains=query) | Q(bio__icontains=query) |
                Q(styles__icontains=query) | Q(workspace__business_name__icontains=query))
        if cat_match:
            cond |= Q(primary_category=cat_match)
        qs = qs.filter(cond)
    if location:
        qs = qs.filter(Q(suburb__icontains=location) | Q(city__icontains=location))

    # Ranking: featured → rating → completeness proxy (has cover/price).
    qs = qs.order_by("-is_featured", "-avg_rating", "-review_count")

    return render(request, "marketplace/search.html", {
        "query": query, "location": location, "category": category, "date": on_date,
        "results": list(qs), "categories": CATEGORIES, "count": qs.count(),
    })


def profile_detail(request, slug):
    workspace = get_object_or_404(
        Workspace.objects.filter(is_published=True).select_related("profile"), slug=slug
    )
    profile = workspace.profile
    # Count a profile view — but not the owner's own visits.
    is_owner = request.user.is_authenticated and request.user.id == workspace.owner_id
    if not is_owner:
        from django.db.models import F
        CreativeProfile.objects.filter(pk=profile.pk).update(view_count=F("view_count") + 1)
    services = workspace.services.prefetch_related("packages")
    packages = [p for s in services for p in s.packages.all()]
    reviews = workspace.reviews.select_related("client").order_by("-created_at")[:6]
    rating_agg = annotate_ratings(CreativeProfile.objects.filter(pk=profile.pk)).first()

    from apps.profiles.services import (availability_calendar, avg_response_hours,
                                        unavailable_dates)
    busy_dates = unavailable_dates(workspace, limit=8)
    measured_response = avg_response_hours(workspace)
    calendar_months = availability_calendar(workspace, months=2)
    is_favourited = (request.user.is_authenticated
                     and Favourite.objects.filter(client=request.user, workspace=workspace).exists())

    return render(request, "marketplace/profile_detail.html", {
        "workspace": workspace, "profile": profile, "packages": packages,
        "reviews": reviews, "categories": CATEGORIES, "busy_dates": busy_dates,
        "avg_rating": getattr(rating_agg, "avg_rating", None),
        "review_count": getattr(rating_agg, "review_count", 0),
        "measured_response": measured_response, "is_favourited": is_favourited,
        "calendar_months": calendar_months,
    })


@login_required
def toggle_favourite(request, slug):
    workspace = get_object_or_404(Workspace, slug=slug, is_published=True)
    fav, created = Favourite.objects.get_or_create(client=request.user, workspace=workspace)
    if created:
        messages.success(request, f"Saved {workspace.business_name} to your favourites.")
    else:
        fav.delete()
        messages.info(request, f"Removed {workspace.business_name} from favourites.")
    return redirect(request.POST.get("next") or reverse("marketplace:profile", args=[slug]))


def enquire(request, slug):
    """Send an enquiry / request a quote.

    No signup wall: logged-out visitors enquire as guests with name + email.
    We auto-create a lightweight account, log them in so they can track it, and
    email a link to set a password and claim it. If the email already has an
    account we attach the enquiry but ask them to log in (no email-only takeover).
    """
    workspace = get_object_or_404(Workspace, slug=slug, is_published=True)
    profile_url = reverse("marketplace:profile", args=[slug])
    if request.method != "POST":
        return redirect(profile_url)

    User = get_user_model()
    redirect_to = reverse("portal:home")

    if request.user.is_authenticated:
        client = request.user
    else:
        email = request.POST.get("email", "").strip().lower()
        name = request.POST.get("name", "").strip()
        phone = request.POST.get("phone", "").strip()
        if not email or "@" not in email:
            messages.error(request, "Please enter your email so the creative can send you a quote.")
            return redirect(profile_url + "#enquire")

        existing = User.objects.filter(email__iexact=email).first()
        if existing:
            client = existing  # attach the enquiry, but make them log in to view it
            _create_from_post(request, client, workspace)
            messages.info(request, "You already have an account with that email — log in to view your enquiry and quote.")
            return redirect(f"{reverse('account_login')}?next={redirect_to}")

        first, _, last = name.partition(" ")
        client = User.objects.create_user(
            email=email, password=None, first_name=first or name, last_name=last,
            phone=phone, role_type=User.RoleType.CLIENT,
        )
        login(request, client, backend="django.contrib.auth.backends.ModelBackend")
        _send_claim_email(request, client)

    _create_from_post(request, client, workspace)
    messages.success(request, f"Enquiry sent to {workspace.business_name}! Track it and your quotes in your portal.")
    return redirect(redirect_to)


def _create_from_post(request, client, workspace):
    create_enquiry(
        client=client, workspace=workspace,
        event_type=request.POST.get("event_type", "weddings"),
        message=request.POST.get("message", "").strip() or "I'd like to enquire about availability.",
        event_date=request.POST.get("event_date") or None,
        location=request.POST.get("location", "").strip(),
        budget_band=request.POST.get("budget_band", "").strip(),
    )


def _send_claim_email(request, user):
    """Let a guest secure their auto-created account (console email in dev)."""
    brand = getattr(settings, "BRAND_NAME", "Lens")
    url = request.build_absolute_uri(reverse("account_reset_password"))
    send_mail(
        subject=f"Your {brand} account",
        message=(
            f"Hi{(' ' + user.first_name) if user.first_name else ''},\n\n"
            f"We created an account for {user.email} so you can track your enquiry, "
            f"review quotes, sign your contract and pay securely.\n\n"
            f"Set a password to secure it here: {url}\n\n— {brand}"
        ),
        from_email=None, recipient_list=[user.email], fail_silently=True,
    )


# Programmatic SEO: suburb × service landing pages -----------------------------
def suburb_service(request, service, suburb):
    from django.http import Http404
    from .geo import SERVICES, SUBURBS_BY_SLUG, creatives_serving, nearby_suburbs

    svc = SERVICES.get(service)
    sub = SUBURBS_BY_SLUG.get(suburb)
    if not svc or not sub:
        raise Http404("Unknown service or suburb")

    results = creatives_serving(suburb, category=svc["category"])
    other_services = [
        {"slug": s, "label": v["label"]} for s, v in SERVICES.items()
        if v["category"] != svc["category"]
    ][:4]
    return render(request, "marketplace/suburb_service.html", {
        "svc": svc, "service_slug": service, "sub": sub, "results": results,
        "count": len(results), "nearby": nearby_suburbs(suburb),
        "other_services": other_services, "categories": CATEGORIES,
    })


def browse(request):
    """Crawlable index linking every service × top suburb (internal linking)."""
    from .geo import SERVICES, SUBURBS
    return render(request, "marketplace/browse.html", {
        "services": [{"slug": s, **v} for s, v in SERVICES.items()],
        "suburbs": [{"name": n, "slug": sl} for n, sl, *_ in SUBURBS],
    })


def health(request):
    """Liveness check for the platform's health probe (Fly.io)."""
    from django.http import HttpResponse
    return HttpResponse("ok", content_type="text/plain")


def calendar_feed(request, token):
    """Read-only iCal feed so a creative can subscribe to their shoots, due dates
    and blocked days from Google/Apple Calendar (calendar sync)."""
    from datetime import timezone as dt_timezone

    from django.conf import settings
    from django.http import Http404, HttpResponse
    from django.utils import timezone

    from apps.bookings.models import CalendarEvent
    from apps.profiles import services as availability
    from apps.workspaces.models import Workspace

    ws = Workspace.objects.filter(ical_token=token).first()
    if not ws:
        raise Http404("Unknown calendar")

    def esc(s):
        return (str(s).replace("\\", "\\\\").replace(",", "\\,")
                .replace(";", "\\;").replace("\n", "\\n"))

    def utc(dt):
        return dt.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    now = timezone.now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             f"PRODID:-//{settings.BRAND_NAME}//Calendar//EN", "CALSCALE:GREGORIAN",
             f"X-WR-CALNAME:{esc(ws.business_name)} — {settings.BRAND_NAME}"]
    for e in CalendarEvent.objects.filter(workspace=ws).select_related("booking"):
        lines += ["BEGIN:VEVENT", f"UID:event-{e.id}@lens", f"DTSTAMP:{now}",
                  f"DTSTART:{utc(e.start)}"]
        if e.end:
            lines.append(f"DTEND:{utc(e.end)}")
        lines.append(f"SUMMARY:{esc(e.title)}")
        if e.booking_id and e.booking.location:
            lines.append(f"LOCATION:{esc(e.booking.location)}")
        lines.append("END:VEVENT")
    for av in availability.blocked_dates(ws):
        lines += ["BEGIN:VEVENT", f"UID:block-{av.id}@lens", f"DTSTAMP:{now}",
                  f"DTSTART;VALUE=DATE:{av.date.strftime('%Y%m%d')}",
                  "SUMMARY:Blocked (unavailable)", "TRANSP:OPAQUE", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return HttpResponse("\r\n".join(lines), content_type="text/calendar; charset=utf-8")


def robots_txt(request):
    from django.http import HttpResponse
    lines = ["User-agent: *", "Allow: /", "Disallow: /app/", "Disallow: /portal/",
             "Disallow: /admin/", "Disallow: /accounts/",
             f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}"]
    return HttpResponse("\n".join(lines), content_type="text/plain")


# Static marketing pages -----------------------------------------------------
def how_it_works(request):
    return render(request, "marketplace/how_it_works.html")


def pricing(request):
    plans = [
        {"name": "Listed", "price": "0", "cadence": "free forever", "for": "New & casual creatives", "featured": False,
         "features": ["Marketplace profile", "Limited enquiries", "Basic calendar", "Portfolio gallery"]},
        {"name": "Pro", "price": "29", "cadence": "per month", "for": "Solo photographers & videographers", "featured": True,
         "features": ["Everything in Listed", "Full CRM & pipeline", "Quotes, contracts & e-sign",
                      "Invoices & deposits (Stripe)", "Gallery delivery", "Mini-website",
                      "AI quote & email drafting", "Full marketplace visibility"]},
        {"name": "Studio", "price": "79", "cadence": "per month", "for": "Studios & teams", "featured": False,
         "features": ["Everything in Pro", "Team seats & roles", "Collaborator tools",
                      "More storage", "Multi-brand (coming)", "Priority support"]},
    ]
    return render(request, "marketplace/pricing.html", {"plans": plans})


def for_creatives(request):
    return render(request, "marketplace/for_creatives.html")


# Legal & support pages ------------------------------------------------------
LEGAL_EFFECTIVE = "15 June 2026"


def privacy(request):
    return render(request, "marketplace/privacy.html", {"effective": LEGAL_EFFECTIVE})


def terms(request):
    return render(request, "marketplace/terms.html", {"effective": LEGAL_EFFECTIVE})


def help_center(request):
    return render(request, "marketplace/help.html")
