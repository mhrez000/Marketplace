from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.bookings import services as flow
from apps.bookings.models import Booking, CalendarEvent
from apps.core.selectors import get_active_workspace
from apps.crm.models import Client
from apps.enquiries.models import Enquiry, Quote
from apps.galleries.models import Asset, Gallery
from apps.messaging.models import Message
from apps.payments.models import Invoice, Payment


def _require_workspace(request):
    """Return the creative's workspace or None (caller redirects)."""
    return get_active_workspace(request.user)


@login_required
def overview(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")

    bookings = Booking.objects.filter(workspace=ws)
    enquiries = Enquiry.objects.filter(workspace=ws)
    revenue = Payment.objects.filter(
        invoice__booking__workspace=ws, status=Payment.Status.SUCCEEDED
    ).aggregate(t=Sum("amount"))["t"] or Decimal("0")

    confirmed = bookings.filter(status__in=[
        Booking.Status.CONFIRMED, Booking.Status.PLANNING, Booking.Status.SHOOT_COMPLETED,
        Booking.Status.EDITING, Booking.Status.DELIVERED, Booking.Status.FINAL_PAID,
    ])
    stats = [
        {"label": "New leads", "value": enquiries.filter(status=Enquiry.Status.NEW).count(), "delta": "live", "up": True},
        {"label": "Quotes sent", "value": Quote.objects.filter(enquiry__workspace=ws, status=Quote.Status.SENT).count(), "delta": "live", "up": True},
        {"label": "Confirmed bookings", "value": confirmed.count(), "delta": "live", "up": True},
        {"label": "Revenue", "value": f"${revenue:,.0f}", "delta": "paid", "up": True},
    ]

    leads = enquiries.select_related("client").order_by("-created_at")[:6]
    upcoming = confirmed.exclude(event_date=None).filter(event_date__gte=timezone.now().date()).order_by("event_date")[:5]

    return render(request, "dashboard/overview.html", {
        "active": "overview", "ws": ws, "stats": stats, "leads": leads,
        "upcoming": upcoming, "bookings_count": bookings.count(),
        "profile_pct": _profile_completeness(ws),
    })


def _profile_completeness(ws):
    score, total = 0, 5
    p = getattr(ws, "profile", None)
    if p:
        if p.bio: score += 1
        if p.headline: score += 1
        if p.starting_price: score += 1
    if ws.services.exists(): score += 1
    if ws.is_verified: score += 1
    return int(score / total * 100)


@login_required
def leads(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    enquiries = Enquiry.objects.filter(workspace=ws).select_related("client").order_by("-created_at")
    return render(request, "dashboard/leads.html", {"active": "leads", "ws": ws, "enquiries": enquiries})


@login_required
def lead_detail(request, pk):
    ws = _require_workspace(request)
    enquiry = get_object_or_404(Enquiry, pk=pk, workspace=ws)
    packages = [p for s in ws.services.prefetch_related("packages") for p in s.packages.all()]

    if request.method == "POST":
        title = request.POST.get("title", "").strip() or f"Quote — {enquiry.get_event_type_display()}"
        line_items = []
        for i in range(1, 5):
            label = request.POST.get(f"label_{i}", "").strip()
            amount = request.POST.get(f"amount_{i}", "").strip()
            if label and amount:
                try:
                    line_items.append({"label": label, "amount": float(amount)})
                except ValueError:
                    continue
        if not line_items:
            messages.error(request, "Add at least one line item with a label and amount.")
        else:
            pkg_id = request.POST.get("package")
            package = next((p for p in packages if str(p.pk) == pkg_id), None)
            deposit_pct = Decimal(request.POST.get("deposit_pct", "25")) / 100
            flow.send_quote(enquiry=enquiry, title=title, line_items=line_items,
                            package=package, deposit_pct=deposit_pct)
            messages.success(request, "Quote sent to the client.")
            return redirect("dashboard:leads")

    return render(request, "dashboard/lead_detail.html", {
        "active": "leads", "ws": ws, "enquiry": enquiry, "packages": packages,
        "quotes": enquiry.quotes.all(),
    })


@login_required
def bookings_list(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    qs = Booking.objects.filter(workspace=ws).select_related("client").order_by("-created_at")
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return render(request, "dashboard/bookings_list.html", {
        "active": "bookings", "ws": ws, "bookings": qs,
        "statuses": Booking.Status.choices, "current_status": status,
    })


@login_required
def booking_detail(request, pk):
    ws = _require_workspace(request)
    booking = get_object_or_404(
        Booking.objects.select_related("client", "quote", "enquiry"), pk=pk, workspace=ws
    )
    contract = getattr(booking, "contract", None)
    invoices = booking.invoices.all()
    galleries = booking.galleries.prefetch_related("assets")
    thread = booking.threads.first() or booking.enquiry.threads.first() if booking.enquiry else None

    if request.method == "POST":
        action = request.POST.get("action")
        _handle_creative_action(request, booking, contract, action)
        return redirect("dashboard:booking_detail", pk=booking.pk)

    return render(request, "dashboard/booking_detail.html", {
        "active": "bookings", "ws": ws, "booking": booking, "contract": contract,
        "invoices": invoices, "galleries": galleries, "thread": thread,
        "messages_list": thread.messages.select_related("sender") if thread else [],
        "S": Booking.Status,
    })


def _handle_creative_action(request, booking, contract, action):
    if action == "sign_contract" and contract and not contract.signed_by_creative_at:
        flow.sign_contract_creative(contract, name=booking.workspace.business_name, request=request)
        messages.success(request, "You signed the contract.")
    elif action == "shoot_completed":
        booking.transition(Booking.Status.SHOOT_COMPLETED, force=True)
        messages.success(request, "Marked shoot as completed.")
    elif action == "start_editing":
        booking.transition(Booking.Status.EDITING, force=True)
        messages.success(request, "Editing started.")
    elif action == "create_gallery":
        _create_demo_gallery(booking)
        messages.success(request, "Gallery created — add it your assets, then deliver.")
    elif action == "deliver_gallery":
        g = booking.galleries.first()
        if g:
            flow.deliver_gallery(g)
            messages.success(request, "Gallery delivered to the client.")
    elif action == "send_final_invoice":
        balance = booking.total - booking.deposit_amount
        Invoice.objects.get_or_create(
            booking=booking, invoice_type=Invoice.Type.FINAL,
            defaults={"amount": balance, "due_date": timezone.now().date(), "status": Invoice.Status.SENT},
        )
        messages.success(request, "Final invoice sent to the client.")
    elif action == "send_message":
        body = request.POST.get("body", "").strip()
        thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)
        if thread and body:
            Message.objects.create(thread=thread, sender=request.user, body=body)


def _create_demo_gallery(booking):
    if booking.galleries.exists():
        return
    g = Gallery.objects.create(
        booking=booking, title=f"{booking.title} — Gallery",
        gallery_type=Gallery.Type.PHOTO, visibility=Gallery.Visibility.PRIVATE,
    )
    accents = ["navy", "teal", "sky"]
    for i in range(9):
        Asset.objects.create(gallery=g, title=f"Image {i+1}", accent=accents[i % 3])
    return g


@login_required
def calendar(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    events = CalendarEvent.objects.filter(workspace=ws).select_related("booking").order_by("start")
    return render(request, "dashboard/calendar.html", {"active": "calendar", "ws": ws, "events": events})


@login_required
def clients(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    client_qs = Client.objects.filter(workspace=ws).select_related("user")
    return render(request, "dashboard/clients.html", {"active": "clients", "ws": ws, "clients": client_qs})


@login_required
def profile(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    p = getattr(ws, "profile", None)
    if request.method == "POST" and p:
        p.headline = request.POST.get("headline", p.headline)
        p.bio = request.POST.get("bio", p.bio)
        p.styles = request.POST.get("styles", p.styles)
        p.starting_price = request.POST.get("starting_price") or p.starting_price
        p.save()
        messages.success(request, "Profile updated.")
        return redirect("dashboard:profile")
    return render(request, "dashboard/profile.html", {"active": "profile", "ws": ws, "profile": p})


@login_required
def onboarding(request):
    """Shown when a logged-in user has no workspace yet (build plan Phase 1)."""
    return render(request, "dashboard/onboarding.html", {"active": "overview"})
