from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.bookings import services as flow
from apps.bookings.models import Booking, CalendarEvent
from apps.core.selectors import get_active_workspace
from apps.crm.models import Client
from apps.enquiries.models import Enquiry, Quote
from apps.galleries.models import Gallery
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
        "prof_items": prof["items"], "prof_remaining": len(prof["missing"]),
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
def hire(request):
    """The creative acting as a *client* — the enquiries and bookings they've
    made TO other creatives. This is the in-dashboard version of the public
    'My portal', so a service provider can book other service providers without
    leaving the dashboard shell. Filters on `client=` (you as the buyer), the
    mirror image of leads/bookings which filter on `workspace=` (you as seller).
    """
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    # Keep statuses fresh (same cheap housekeeping the public portal does).
    from apps.enquiries.services import expire_quotes
    from apps.payments.services import mark_overdue_invoices
    expire_quotes()
    mark_overdue_invoices()

    enquiries = (Enquiry.objects.filter(client=request.user)
                 .select_related("workspace").prefetch_related("quotes").order_by("-created_at"))
    bookings = (Booking.objects.filter(client=request.user)
                .select_related("workspace").order_by("-created_at"))
    from apps.core.selectors import annotate_ratings
    fav_ids = request.user.favourites.values_list("workspace_id", flat=True)
    saved = annotate_ratings(
        CreativeProfile.objects.filter(workspace_id__in=fav_ids, workspace__is_published=True)
        .select_related("workspace"))
    return render(request, "dashboard/hire.html", {
        "active": "hire", "ws": ws,
        "enquiries": enquiries, "bookings": bookings, "saved": saved,
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
    thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)

    if request.method == "POST":
        action = request.POST.get("action")
        _handle_creative_action(request, booking, contract, action)
        return redirect("dashboard:booking_detail", pk=booking.pk)

    from apps.payments.services import compute_refund
    from apps.bookings.models import BookingCollaborator, Dispute
    collaborators = booking.collaborators.exclude(
        status=BookingCollaborator.Status.REMOVED).select_related("workspace")
    # Creatives A can invite: any other published workspace not already on the booking.
    on_booking = booking.collaborators.values_list("workspace_id", flat=True)
    pickable = (Workspace.objects.filter(is_published=True)
                .exclude(pk=ws.pk).exclude(pk__in=on_booking).order_by("business_name"))
    return render(request, "dashboard/booking_detail.html", {
        "active": "bookings", "ws": ws, "booking": booking, "contract": contract,
        "invoices": invoices, "galleries": galleries, "thread": thread,
        "messages_list": thread.messages.select_related("sender") if thread else [],
        "S": Booking.Status, "refund": compute_refund(booking),
        "dispute": booking.disputes.order_by("-created_at").first(),
        "dispute_reasons": Dispute.Reason.choices,
        "collaborators": collaborators, "pickable_creatives": pickable,
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
    elif action == "deliver_link":
        url = request.POST.get("delivery_url", "").strip()
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError
        try:
            URLValidator(schemes=["http", "https"])(url)
        except ValidationError:
            messages.error(request, "Please paste a valid link (starting with https://).")
        else:
            title = request.POST.get("title", "").strip() or f"{booking.title} — Gallery"
            g = Gallery.objects.create(
                booking=booking, title=title, delivery_url=url,
                gallery_type=Gallery.Type.PHOTO, visibility=Gallery.Visibility.PRIVATE,
            )
            flow.deliver_gallery(g)
            messages.success(request, f"Gallery link delivered to {booking.client.email}.")
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
    elif action == "raise_dispute":
        flow.raise_dispute(booking, user=request.user, role="creative",
                           reason=request.POST.get("reason", "other"),
                           detail=request.POST.get("detail", "").strip())
        messages.success(request, "Dispute raised — our team will review it.")
    elif action == "send_message":
        body = request.POST.get("body", "").strip()
        thread = booking.threads.first() or (booking.enquiry.threads.first() if booking.enquiry else None)
        if thread and body:
            Message.objects.create(thread=thread, sender=request.user, body=body)
            if thread.enquiry:  # creative replying counts as a response
                thread.enquiry.mark_responded()
    elif action == "add_collaborator":
        _add_collaborator(request, booking)
    elif action == "pay_collaborator":
        _collab_action(request, booking, flow.pay_collaborator, "Collaborator paid.")
    elif action == "remove_collaborator":
        _collab_action(request, booking, flow.remove_collaborator, "Collaborator removed.")


def _add_collaborator(request, booking):
    ws_id = request.POST.get("collab_workspace")
    target = Workspace.objects.filter(pk=ws_id, is_published=True).first()
    if not target:
        messages.error(request, "Pick a creative to collaborate with.")
        return
    fee_raw = (request.POST.get("fee") or "0").strip()
    try:
        fee = Decimal(fee_raw or "0")
    except Exception:
        messages.error(request, "Enter a valid fee amount.")
        return
    try:
        flow.invite_collaborator(booking, target, role=request.POST.get("role", "").strip(),
                                 fee=fee, by=request.user)
    except flow.CollaborationError as e:
        messages.error(request, str(e))
        return
    messages.success(request, f"Invited {target.business_name} to collaborate.")


def _collab_action(request, booking, fn, ok_msg):
    from apps.bookings.models import BookingCollaborator
    collab = BookingCollaborator.objects.filter(
        pk=request.POST.get("collab_id"), booking=booking).first()
    if not collab:
        return
    try:
        fn(collab)
    except flow.CollaborationError as e:
        messages.error(request, str(e))
        return
    messages.success(request, ok_msg)


@login_required
def collaborations(request):
    """B's side: invites to accept/decline + active collaborations, across every
    workspace this user owns. The mirror of A managing collaborators on a booking."""
    from apps.bookings.models import BookingCollaborator
    ws_ids = list(request.user.owned_workspaces.values_list("id", flat=True))

    if request.method == "POST":
        action = request.POST.get("action")
        collab = BookingCollaborator.objects.filter(
            pk=request.POST.get("collab_id"), workspace_id__in=ws_ids).first()
        if collab and collab.is_pending and action in ("accept", "decline"):
            flow.respond_collaboration(collab, accept=(action == "accept"))
            messages.success(request, "Collaboration accepted." if action == "accept"
                             else "Invite declined.")
        return redirect("dashboard:collaborations")

    qs = (BookingCollaborator.objects.filter(workspace_id__in=ws_ids)
          .exclude(status=BookingCollaborator.Status.REMOVED)
          .select_related("booking", "booking__workspace").order_by("-created_at"))
    return render(request, "dashboard/collaborations.html", {
        "active": "collaborations", "ws": _require_workspace(request),
        "pending": [c for c in qs if c.is_pending],
        "active_collabs": [c for c in qs if c.is_active],
    })


@login_required
def collaboration_detail(request, pk):
    """B's REDACTED view of a booking they're collaborating on: the job logistics
    (date, location, scope), who hired them, and their own fee — but never the
    client's identity, and with no way to message the client."""
    from apps.bookings.models import BookingCollaborator
    ws_ids = list(request.user.owned_workspaces.values_list("id", flat=True))
    collab = get_object_or_404(
        BookingCollaborator.objects.select_related("booking", "booking__workspace"),
        pk=pk, workspace_id__in=ws_ids, status=BookingCollaborator.Status.ACCEPTED)
    return render(request, "dashboard/collaboration_detail.html", {
        "active": "collaborations", "ws": _require_workspace(request),
        "collab": collab, "booking": collab.booking,
    })


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
        elif action == "add_event":
            _add_personal_event(request, ws)
        elif action == "delete_event":
            CalendarEvent.objects.filter(
                pk=request.POST.get("event_id"), workspace=ws,
                event_type=CalendarEvent.Type.CUSTOM).delete()
            messages.success(request, "Event removed.")
        return redirect("dashboard:calendar")

    return render(request, "dashboard/calendar.html", {
        "active": "calendar", "ws": ws,
        "blocked": availability.blocked_dates(ws),
        "today": timezone.now().date(),
    })


def _add_personal_event(request, ws):
    """Create a creative's own (non-booking) calendar event — a hold or reminder."""
    from datetime import datetime

    title = request.POST.get("title", "").strip()
    date_str = request.POST.get("event_date", "").strip()
    if not title or not date_str:
        messages.error(request, "An event needs a title and a date.")
        return
    time_str = request.POST.get("event_time", "").strip() or "09:00"
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        messages.error(request, "Couldn't read that date or time.")
        return
    CalendarEvent.objects.create(
        workspace=ws, event_type=CalendarEvent.Type.CUSTOM, title=title,
        start=timezone.make_aware(naive))
    messages.success(request, f"Added “{title}” to your calendar.")


@login_required
def calendar_events(request):
    """JSON feed for FullCalendar: shoots, due dates and blocked days."""
    from django.http import JsonResponse
    ws = _require_workspace(request)
    if not ws:
        return JsonResponse([], safe=False)

    T = CalendarEvent.Type
    colors = {
        T.SHOOT: "#2F4156", T.EDITING_DUE: "#567C8D", T.PAYMENT_DUE: "#b7791f",
        T.CONTRACT_DUE: "#84a4c0", T.BLOCKED: "#9aabc0", T.CUSTOM: "#8b6f9e",
    }
    icons = {T.SHOOT: "📷", T.EDITING_DUE: "🖼", T.PAYMENT_DUE: "💰",
             T.CONTRACT_DUE: "📄", T.CUSTOM: "📌"}
    # Bookings (the shoot itself) vs tasks (deadlines you owe) vs your own holds.
    category = {
        T.SHOOT: "shoot", T.EDITING_DUE: "task", T.PAYMENT_DUE: "task",
        T.CONTRACT_DUE: "task", T.BLOCKED: "blocked", T.CUSTOM: "personal",
    }
    out = []
    for e in CalendarEvent.objects.filter(workspace=ws).select_related("booking"):
        cat = category.get(e.event_type, "task")
        out.append({
            "id": str(e.id),
            "title": f"{icons.get(e.event_type, '')} {e.title}".strip(),
            "start": e.start.isoformat(),
            "end": e.end.isoformat() if e.end else None,
            "color": colors.get(e.event_type, "#2F4156"),
            # Shoots & personal holds render as solid blocks; deadlines as a dot.
            "display": "block" if cat in ("shoot", "personal") else "list-item",
            "classNames": [f"cat-{cat}"],
            "extendedProps": {
                "category": cat,
                "kind": e.get_event_type_display(),
                "overdue": e.is_overdue,
                "deletable": e.event_type == T.CUSTOM,
                "bookingUrl": reverse("dashboard:booking_detail", args=[e.booking_id]) if e.booking_id else "",
                "bookingTitle": e.booking.title if e.booking_id else "",
                "location": e.booking.location if e.booking_id else "",
                "status": e.booking.get_status_display() if e.booking_id else "",
            },
        })
    # Blocked days as all-day background blocks.
    for av in availability.blocked_dates(ws):
        out.append({
            "start": av.date.isoformat(), "allDay": True, "display": "background",
            "color": "#e7d9c9", "title": "Blocked", "classNames": ["cat-blocked"],
            "extendedProps": {"category": "blocked"},
        })
    return JsonResponse(out, safe=False)


@login_required
def deliveries(request):
    """Post-shoot production & delivery tracker — what's due, what's overdue,
    and reminders for every job after the shoot (build research)."""
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")

    if request.method == "POST":
        action = request.POST.get("action")
        booking_q = request.POST.get("booking", "")
        if action == "add_task":
            b = get_object_or_404(Booking, pk=booking_q, workspace=ws)
            title = request.POST.get("title", "").strip()
            if title:
                due = request.POST.get("due_date") or None
                Deliverable.objects.create(
                    booking=b, workspace=ws, kind=Deliverable.Kind.CUSTOM, title=title,
                    due_date=due, sort_order=b.deliverables.count())
                messages.success(request, f"Added “{title}”.")
            return redirect(f"{reverse('dashboard:deliveries')}?booking={b.pk}")
        if action == "apply_checklist":
            b = get_object_or_404(Booking, pk=booking_q, workspace=ws)
            n = prod.add_custom_tasks(b)
            messages.success(request, f"Added {n} task(s) from your checklist." if n
                             else "No new checklist tasks to add (or none defined yet).")
            return redirect(f"{reverse('dashboard:deliveries')}?booking={b.pk}")

        d = get_object_or_404(Deliverable, pk=request.POST.get("deliverable"), workspace=ws)
        back = f"{reverse('dashboard:deliveries')}?booking={d.booking_id}"
        if action == "done":
            d.mark_done()
        elif action == "reopen":
            d.reopen()
        elif action == "delete":
            d.delete()
        elif action == "snooze" and d.due_date:
            d.due_date += timezone.timedelta(days=7)
            d.reminded_at = None
            d.save(update_fields=["due_date", "reminded_at", "updated_at"])
        return redirect(back)

    # Make sure existing bookings have a delivery plan, then raise reminders.
    prod.backfill_for_workspace(ws)
    prod.generate_reminders(ws)

    items = list(Deliverable.objects.filter(workspace=ws).select_related("booking", "booking__client"))
    active = [d for d in items if not d.is_done]
    overdue = [d for d in active if d.is_overdue]
    due_soon = [d for d in active if not d.is_overdue and d.is_due_soon]
    counts = {"overdue": len(overdue), "due_soon": len(due_soon),
              "upcoming": len([d for d in active if not d.is_overdue and not d.is_due_soon]),
              "done": len([d for d in items if d.is_done])}

    # Per-booking groups (the left list + the right panel content).
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
                    key=lambda g: (g["overdue_count"] == 0, g["next_due"] is None,
                                   g["next_due"] or timezone.now().date()))

    # Which booking's tasks to show on the right (default: most urgent).
    selected_id = request.GET.get("booking")
    selected = next((g for g in groups if str(g["booking"].pk) == selected_id), None)
    if selected is None and groups:
        selected = groups[0]

    ctx = {"active": "deliveries", "ws": ws, "groups": groups, "selected": selected,
           "counts": counts}
    if request.GET.get("panel"):
        return render(request, "dashboard/_deliverable_panel.html", ctx)
    return render(request, "dashboard/deliveries.html", ctx)


@login_required
def checklist(request):
    """Manage the workspace's reusable delivery checklist (applied to new jobs)."""
    from apps.production.models import DeliverableTemplate
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            label = request.POST.get("label", "").strip()
            if label:
                try:
                    offset = int(request.POST.get("day_offset") or 7)
                except ValueError:
                    offset = 7
                DeliverableTemplate.objects.create(
                    workspace=ws, label=label, day_offset=offset,
                    is_client_facing="is_client_facing" in request.POST,
                    sort_order=ws.task_templates.count())
                messages.success(request, "Task added to your checklist.")
        elif action == "delete":
            ws.task_templates.filter(pk=request.POST.get("id")).delete()
        return redirect("dashboard:checklist")
    return render(request, "dashboard/checklist.html", {
        "active": "profile", "ws": ws, "templates": ws.task_templates.all()})


@login_required
def ops(request):
    """Staff-only ops dashboard — today's platform pulse (build plan §13):
    GMV, bookings, enquiries, open disputes, overdue invoices, pending
    approvals, and the latest activity."""
    from django.http import Http404

    if not request.user.is_staff:
        raise Http404

    from apps.bookings.models import Dispute
    from apps.profiles.models import VerificationDocument

    today = timezone.now().date()
    week_ago = timezone.now() - timezone.timedelta(days=7)

    payments = Payment.objects.filter(status=Payment.Status.SUCCEEDED)
    gmv_total = payments.aggregate(s=Sum("amount"))["s"] or 0
    gmv_week = payments.filter(paid_at__gte=week_ago).aggregate(s=Sum("amount"))["s"] or 0
    fees_total = payments.aggregate(s=Sum("platform_fee"))["s"] or 0

    stats = [
        {"label": "GMV (all time)", "value": f"${gmv_total:,.0f}"},
        {"label": "GMV (7 days)", "value": f"${gmv_week:,.0f}"},
        {"label": "Platform fees", "value": f"${fees_total:,.0f}"},
        {"label": "Enquiries (7d)", "value": Enquiry.objects.filter(created_at__gte=week_ago).count()},
    ]

    from django.contrib.auth import get_user_model

    pending_ws = Workspace.objects.filter(is_published=False)
    pending_docs = VerificationDocument.objects.filter(status=VerificationDocument.Status.PENDING)
    open_disputes = Dispute.objects.filter(status__in=["open", "under_review"]).select_related("booking", "raised_by")
    overdue_invoices = Invoice.objects.filter(status=Invoice.Status.OVERDUE).select_related("booking")

    return render(request, "dashboard/ops.html", {
        "active": "ops", "ws": get_active_workspace(request.user), "stats": stats,
        "pending_ws": pending_ws, "pending_docs_count": pending_docs.count(),
        "open_disputes": open_disputes, "overdue_invoices": overdue_invoices,
        "recent_bookings": Booking.objects.select_related("client", "workspace").order_by("-created_at")[:8],
        "todays_shoots": Booking.objects.filter(event_date=today).select_related("workspace", "client"),
        "signups_week": get_user_model().objects.filter(date_joined__gte=week_ago).count(),
    })


@login_required
def broadcast(request):
    """Staff-only: send a platform announcement to a target audience."""
    from django.http import Http404
    from apps.notifications.models import Broadcast, resolve_audience
    from apps.notifications.tasks import send_broadcast

    if not request.user.is_staff:
        raise Http404

    if request.method == "POST":
        b = Broadcast.objects.create(
            sender=request.user,
            audience=request.POST.get("audience", Broadcast.Audience.ALL),
            title=request.POST.get("title", "").strip(),
            body=request.POST.get("body", "").strip(),
            url=request.POST.get("url", "").strip(),
            send_email="send_email" in request.POST,
        )
        if not b.title or not b.body:
            b.delete()
            messages.error(request, "A title and message are required.")
        else:
            n = resolve_audience(b.audience).count()
            send_broadcast.delay(b.id)
            messages.success(request, f"Broadcast sent to {n} {b.get_audience_display().lower()}"
                                      f"{' (with email)' if b.send_email else ''}.")
            return redirect("dashboard:broadcast")

    return render(request, "dashboard/broadcast.html", {
        "active": "broadcast", "ws": get_active_workspace(request.user),
        "audiences": [{"value": a, "label": label, "count": resolve_audience(a).count()}
                      for a, label in Broadcast.Audience.choices],
        "past": Broadcast.objects.select_related("sender").order_by("-created_at")[:10],
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
def analytics(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    from apps.dashboard.analytics import workspace_analytics
    return render(request, "dashboard/analytics.html", {
        "active": "analytics", "ws": ws, "a": workspace_analytics(ws),
    })


@login_required
def search(request):
    """The header search — finds the creative's leads, clients and bookings."""
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    q = request.GET.get("q", "").strip()
    leads = clients = bookings = []
    if q:
        from apps.crm.models import Client
        person = (Q(client__first_name__icontains=q) | Q(client__last_name__icontains=q)
                  | Q(client__email__icontains=q))
        leads = (Enquiry.objects.filter(workspace=ws).filter(person | Q(message__icontains=q))
                 .select_related("client").order_by("-created_at")[:12])
        clients = (Client.objects.filter(workspace=ws)
                   .filter(Q(name__icontains=q) | Q(email__icontains=q)).order_by("name")[:12])
        bookings = (Booking.objects.filter(workspace=ws).filter(person | Q(title__icontains=q))
                    .select_related("client").order_by("-created_at")[:12])
    return render(request, "dashboard/search.html", {
        "active": "", "ws": ws, "q": q, "leads": leads, "clients": clients, "bookings": bookings})


@login_required
def profile(request):
    ws = _require_workspace(request)
    if not ws:
        return redirect("dashboard:onboarding")
    p = getattr(ws, "profile", None)
    if request.method == "POST" and p:
        action = request.POST.get("action")
        if action in {"add_package", "edit_package", "delete_package"}:
            _handle_package_action(request, ws, p, action)
            return redirect("dashboard:profile")
        p.headline = request.POST.get("headline", p.headline)
        p.bio = request.POST.get("bio", p.bio)
        p.styles = request.POST.get("styles", p.styles)
        p.starting_price = request.POST.get("starting_price") or p.starting_price
        p.save()
        messages.success(request, "Profile updated.")
        return redirect("dashboard:profile")
    packages = Package.objects.filter(service__workspace=ws).select_related("service")
    sub = Subscription.objects.filter(workspace=ws).first()
    return render(request, "dashboard/profile.html", {
        "active": "profile", "ws": ws, "profile": p, "packages": packages,
        "plan_display": sub.get_plan_display() if sub else "Free",
        "completeness": availability.completeness(ws),
    })


def _handle_package_action(request, ws, profile, action):
    if action == "delete_package":
        Package.objects.filter(pk=request.POST.get("package_id"), service__workspace=ws).delete()
        messages.success(request, "Package removed.")
        return

    name = request.POST.get("name", "").strip()
    price_raw = request.POST.get("base_price", "").strip()
    try:
        price = Decimal(price_raw) if price_raw else None
    except (ValueError, ArithmeticError):
        price = None

    if action == "edit_package":
        pkg = get_object_or_404(Package, pk=request.POST.get("package_id"), service__workspace=ws)
        if name:
            pkg.name = name
        if price is not None:
            pkg.base_price = price
        pkg.description = request.POST.get("description", pkg.description).strip()
        pkg.inclusions = request.POST.get("inclusions", pkg.inclusions)
        pkg.save()
        messages.success(request, f"Updated “{pkg.name}”.")
        return

    # add_package
    if not name or price is None:
        messages.error(request, "A package needs a name and a price.")
        return
    service = ws.services.first() or Service.objects.create(
        workspace=ws, category=profile.primary_category, title=ws.business_name)
    Package.objects.create(
        service=service, name=name, base_price=price,
        description=request.POST.get("description", "").strip(),
        inclusions=request.POST.get("inclusions", "").strip())
    messages.success(request, f"Added “{name}”.")


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
