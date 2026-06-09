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
from apps.payments.models import Invoice, Payment, Subscription
from apps.production import services as prod
from apps.production.models import Deliverable
from apps.profiles import services as availability
from apps.profiles.models import (CATEGORY_CHOICES, CreativeProfile, Package,
                                  Service)
from apps.workspaces.models import Member, Workspace


def _require_workspace(request):
    """Return the creative's workspace or None (caller redirects)."""
    return get_active_workspace(request.user)


@login_required
def overview(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")

    from apps.enquiries.services import expire_quotes
    from apps.payments.services import mark_overdue_invoices
    expire_quotes()
    mark_overdue_invoices()

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

    new_leads = enquiries.filter(status=Enquiry.Status.NEW)
    stale_leads = sum(1 for e in new_leads if e.is_stale)
    avg_resp = availability.avg_response_hours(ws)

    from django.db.models import Avg, Count
    from apps.reviews.models import Review
    review_agg = Review.objects.filter(workspace=ws).aggregate(n=Count("id"), avg=Avg("rating"))
    pending_reviews = sum(1 for b in bookings.filter(status=Booking.Status.COMPLETED) if b.awaiting_review)
    prof = availability.completeness(ws)

    return render(request, "dashboard/overview.html", {
        "active": "overview", "ws": ws, "stats": stats, "leads": leads,
        "upcoming": upcoming, "bookings_count": bookings.count(),
        "profile_pct": prof["pct"], "prof_listable": prof["listable"],
        "stale_leads": stale_leads, "avg_response": avg_resp,
        "review_count": review_agg["n"], "avg_review": review_agg["avg"],
        "pending_reviews": pending_reviews,
    })


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


# Group the 16 pipeline statuses into the natural stages for a tidy filter bar.
_S = Booking.Status
BOOKING_GROUPS = [
    ("leads", "Leads", [_S.NEW, _S.QUOTE_SENT, _S.QUOTE_ACCEPTED]),
    ("booked", "Booked", [_S.CONTRACT_SENT, _S.CONTRACT_SIGNED, _S.DEPOSIT_PAID,
                          _S.CONFIRMED, _S.PLANNING]),
    ("production", "In production", [_S.SHOOT_COMPLETED, _S.EDITING]),
    ("delivered", "Delivered", [_S.DELIVERED, _S.FINAL_PAID]),
    ("completed", "Completed", [_S.COMPLETED, _S.ARCHIVED]),
    ("cancelled", "Cancelled", [_S.CANCELLED, _S.REFUNDED]),
]
_GROUP_MAP = {key: statuses for key, _label, statuses in BOOKING_GROUPS}


@login_required
def bookings_list(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    base = Booking.objects.filter(workspace=ws).select_related("client")

    group = request.GET.get("group")
    groups = [
        {"key": key, "label": label, "count": base.filter(status__in=statuses).count()}
        for key, label, statuses in BOOKING_GROUPS
    ]
    qs = base.order_by("-created_at")
    if group in _GROUP_MAP:
        qs = qs.filter(status__in=_GROUP_MAP[group])

    return render(request, "dashboard/bookings_list.html", {
        "active": "bookings", "ws": ws, "bookings": qs,
        "groups": groups, "current_group": group, "total_count": base.count(),
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

    from apps.payments.services import compute_refund
    return render(request, "dashboard/booking_detail.html", {
        "active": "bookings", "ws": ws, "booking": booking, "contract": contract,
        "invoices": invoices, "galleries": galleries, "thread": thread,
        "messages_list": thread.messages.select_related("sender") if thread else [],
        "S": Booking.Status, "refund": compute_refund(booking),
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
    elif action == "cancel":
        flow.cancel_booking(booking, by="creative", reason=request.POST.get("reason", "").strip())
        messages.success(request, "Booking cancelled and the date freed up.")
    elif action == "send_message":
        body = request.POST.get("body", "").strip()
        thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)
        if thread and body:
            Message.objects.create(thread=thread, sender=request.user, body=body)
            if thread.enquiry:  # creative replying counts as a response
                thread.enquiry.mark_responded()


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

    if request.method == "POST":
        action = request.POST.get("action")
        on_date = request.POST.get("date")
        if action == "block" and on_date:
            if availability.block(ws, on_date):
                messages.success(request, f"Blocked {on_date}.")
            else:
                messages.error(request, "That date is already booked — can't block it.")
        elif action == "unblock" and on_date:
            availability.unblock(ws, on_date)
            messages.success(request, f"Unblocked {on_date}.")
        return redirect("dashboard:calendar")

    events = CalendarEvent.objects.filter(workspace=ws).select_related("booking").order_by("start")
    return render(request, "dashboard/calendar.html", {
        "active": "calendar", "ws": ws, "events": events,
        "blocked": availability.blocked_dates(ws),
        "booked": availability.unavailable_dates(ws, limit=30),
        "today": timezone.now().date(),
    })


@login_required
def deliveries(request):
    """Post-shoot production & delivery tracker — what's due, what's overdue,
    and reminders for every job after the shoot (build research)."""
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")

    if request.method == "POST":
        action = request.POST.get("action")
        d = get_object_or_404(Deliverable, pk=request.POST.get("deliverable"), workspace=ws)
        if action == "done":
            d.mark_done()
            messages.success(request, f"Marked “{d.title}” as done.")
        elif action == "reopen":
            d.reopen()
        elif action == "snooze":
            if d.due_date:
                d.due_date += timezone.timedelta(days=7)
                d.reminded_at = None
                d.save(update_fields=["due_date", "reminded_at", "updated_at"])
                messages.success(request, f"Pushed “{d.title}” back a week.")
        elif action == "set_due":
            new_due = request.POST.get("due_date")
            if new_due:
                d.due_date = new_due
                d.reminded_at = None
                d.save(update_fields=["due_date", "reminded_at", "updated_at"])
        return redirect("dashboard:deliveries")

    # Make sure existing bookings have a delivery plan, then raise reminders.
    prod.backfill_for_workspace(ws)
    prod.generate_reminders(ws)

    items = list(Deliverable.objects.filter(workspace=ws).select_related("booking", "booking__client"))
    active = [d for d in items if not d.is_done]
    overdue = sorted([d for d in active if d.is_overdue], key=lambda d: d.due_date or timezone.now().date())
    due_soon = sorted([d for d in active if not d.is_overdue and d.is_due_soon],
                      key=lambda d: d.due_date or timezone.now().date())
    upcoming = sorted([d for d in active if not d.is_overdue and not d.is_due_soon],
                      key=lambda d: d.due_date or timezone.now().date())
    done = [d for d in items if d.is_done]

    # Per-booking timelines, sorted by nearest open due date.
    by_booking = {}
    for d in items:
        by_booking.setdefault(d.booking_id, {"booking": d.booking, "items": []})["items"].append(d)
    for grp in by_booking.values():
        grp["items"].sort(key=lambda x: (x.sort_order, x.due_date or timezone.now().date()))
        open_items = [x for x in grp["items"] if not x.is_done]
        grp["next_due"] = min((x.due_date for x in open_items if x.due_date), default=None)
        grp["open_count"] = len(open_items)
        grp["overdue_count"] = len([x for x in open_items if x.is_overdue])
    groups = sorted(by_booking.values(),
                    key=lambda g: (g["next_due"] is None, g["next_due"] or timezone.now().date()))

    flt = request.GET.get("filter", "attention")
    return render(request, "dashboard/deliveries.html", {
        "active": "deliveries", "ws": ws,
        "overdue": overdue, "due_soon": due_soon, "upcoming": upcoming, "done": done,
        "attention": overdue + due_soon, "groups": groups, "filter": flt,
        "counts": {"overdue": len(overdue), "due_soon": len(due_soon),
                   "upcoming": len(upcoming), "done": len(done)},
    })


@login_required
def notifications_read(request):
    """Mark all of the current user's notifications read."""
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect(request.POST.get("next") or request.META.get("HTTP_REFERER") or "dashboard:overview")


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
    return render(request, "dashboard/profile.html", {
        "active": "profile", "ws": ws, "profile": p,
        "completeness": availability.completeness(ws),
    })


@login_required
def onboarding(request):
    """Create-your-workspace wizard, shown when a user has no workspace yet
    (build plan Phase 1). Spins up a workspace + profile + first package so
    every dashboard tab becomes usable immediately."""
    if get_active_workspace(request.user):
        return redirect("dashboard:overview")

    if request.method == "POST":
        business = request.POST.get("business_name", "").strip()
        if not business:
            messages.error(request, "Please enter a business name.")
        else:
            category = request.POST.get("category", "weddings")
            ws = Workspace.objects.create(
                owner=request.user, type=Workspace.Type.SOLO, business_name=business,
                abn=request.POST.get("abn", "").strip(), is_published=True,
            )
            ws.mark_verified()  # demo: auto-verify so the public page works right away
            Member.objects.create(workspace=ws, user=request.user, role=Member.Role.OWNER)
            Subscription.objects.create(
                workspace=ws, plan=Subscription.Plan.PRO,
                period_end=timezone.now().date() + timezone.timedelta(days=300),
            )
            if request.user.role_type == "client":
                request.user.role_type = "creative"
                request.user.save(update_fields=["role_type"])

            CreativeProfile.objects.create(
                workspace=ws,
                headline=request.POST.get("headline", "").strip(),
                bio=request.POST.get("bio", "").strip(),
                suburb=request.POST.get("suburb", "").strip(),
                primary_category=category,
                styles=request.POST.get("styles", "").strip(),
                starting_price=Decimal(request.POST.get("starting_price") or "0"),
                accent=request.POST.get("accent", "navy"),
            )
            svc = Service.objects.create(
                workspace=ws, category=category,
                title=f"{business} — {dict(CATEGORY_CHOICES).get(category, 'Services')}",
            )
            pkg_name = request.POST.get("package_name", "").strip()
            pkg_price = request.POST.get("package_price", "").strip()
            if pkg_name and pkg_price:
                try:
                    Package.objects.create(service=svc, name=pkg_name,
                                           base_price=Decimal(pkg_price))
                except (ValueError, ArithmeticError):
                    pass
            messages.success(request, f"{business} is live! Your dashboard is ready.")
            return redirect("dashboard:overview")

    return render(request, "dashboard/onboarding.html", {
        "active": "overview", "categories": CATEGORY_CHOICES,
    })
