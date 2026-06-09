"""Orchestration for the transactional spine.

Each function performs one step of: enquiry → quote → accept → contract →
deposit → confirmed → … → delivered → final → completed → review. Side effects
(invoices, calendar events, availability, notifications) live here so views stay
thin and the flow is testable in one place.
"""
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.contracts.models import Contract, ContractTemplate
from apps.crm.models import Client
from apps.enquiries.models import Enquiry, Quote
from apps.galleries.models import Gallery
from apps.messaging.models import Message, Thread
from apps.notifications.models import notify
from apps.payments.models import Invoice, Payment
from apps.payments.services import charge_invoice
from apps.profiles import services as availability
from apps.profiles.models import Availability
from apps.reviews.models import Review

from .models import Booking, CalendarEvent


class DateUnavailable(Exception):
    """Raised when trying to confirm a booking on a date that's already taken."""

    def __init__(self, event_date):
        self.event_date = event_date
        super().__init__(f"{event_date} is no longer available.")


# ── Enquiry ────────────────────────────────────────────────────────────────
def create_enquiry(*, client, workspace, event_type, message, event_date=None,
                   location="", budget_band="", source="marketplace"):
    enquiry = Enquiry.objects.create(
        client=client, workspace=workspace, event_type=event_type, message=message,
        event_date=event_date, location=location, budget_band=budget_band, source=source,
    )
    # Ensure a CRM client record + a message thread exist.
    Client.objects.get_or_create(
        workspace=workspace, user=client,
        defaults={"name": client.get_full_name() or client.email, "email": client.email,
                  "lead_source": source},
    )
    thread, _ = Thread.objects.get_or_create(
        workspace=workspace, client=client, enquiry=enquiry,
        defaults={"subject": f"{enquiry.get_event_type_display()} enquiry"},
    )
    if message:
        Message.objects.create(thread=thread, sender=client, body=message)
    notify(workspace.owner, f"New enquiry from {client.email}", url="/app/leads/", icon="inbox", email=True)
    return enquiry


# ── Quote ──────────────────────────────────────────────────────────────────
def send_quote(*, enquiry, title, line_items, package=None, deposit_pct=Decimal("0.25"),
               valid_days=14):
    quote = Quote(
        enquiry=enquiry, package=package, title=title, line_items=line_items,
        status=Quote.Status.SENT, expires_at=timezone.now().date() + timedelta(days=valid_days),
    )
    quote.recalc(deposit_pct=deposit_pct)
    quote.save()
    enquiry.mark_responded()  # sending a quote counts as the first response
    enquiry.status = Enquiry.Status.QUOTED
    enquiry.save(update_fields=["status", "updated_at"])
    notify(enquiry.client, f"You received a quote from {enquiry.workspace.business_name}", email=True,
           url="/portal/", icon="doc")
    return quote


# ── Accept quote → Booking + Contract ──────────────────────────────────────
def accept_quote(quote):
    enquiry = quote.enquiry
    quote.status = Quote.Status.ACCEPTED
    quote.save(update_fields=["status", "updated_at"])
    enquiry.status = Enquiry.Status.ACCEPTED
    enquiry.save(update_fields=["status", "updated_at"])

    booking = Booking.objects.create(
        enquiry=enquiry, quote=quote, client=enquiry.client, workspace=enquiry.workspace,
        status=Booking.Status.QUOTE_ACCEPTED,
        title=f"{enquiry.get_event_type_display()} — {enquiry.client.get_full_name() or enquiry.client.email}",
        event_date=enquiry.event_date, location=enquiry.location,
        total=quote.total, deposit_amount=quote.deposit_amount,
    )
    _generate_contract(booking)
    booking.transition(Booking.Status.CONTRACT_SENT)
    notify(enquiry.workspace.owner, f"{enquiry.client.email} accepted your quote", url="/app/bookings/", icon="card")
    notify(enquiry.client, "Please review & sign your contract", url=f"/portal/booking/{booking.id}/", icon="doc", email=True)
    return booking


def _generate_contract(booking):
    template = ContractTemplate.objects.filter(
        contract_type=_template_type(booking)
    ).first() or ContractTemplate.objects.first()
    body = _render_contract_body(template, booking)
    return Contract.objects.create(
        booking=booking, template=template,
        title=f"Service Agreement — {booking.workspace.business_name}", body=body,
    )


def _template_type(booking):
    et = booking.enquiry.event_type if booking.enquiry else "events"
    return {"weddings": "wedding", "real-estate": "real_estate",
            "business": "commercial"}.get(et, "events")


def _render_contract_body(template, booking):
    raw = template.body if template else DEFAULT_CONTRACT
    return (raw
            .replace("{{client_name}}", booking.client.get_full_name() or booking.client.email)
            .replace("{{business_name}}", booking.workspace.business_name)
            .replace("{{event_date}}", booking.event_date.strftime("%d %B %Y") if booking.event_date else "TBC")
            .replace("{{total}}", f"${booking.total:,.2f}")
            .replace("{{deposit}}", f"${booking.deposit_amount:,.2f}"))


# ── Sign contract ──────────────────────────────────────────────────────────
def sign_contract_client(contract, *, name, request=None):
    contract.client_signature_name = name
    contract.signed_by_client_at = timezone.now()
    contract.audit.append(_audit_entry("client", name, request))
    contract.save()
    booking = contract.booking
    booking.transition(Booking.Status.CONTRACT_SIGNED)
    _ensure_deposit_invoice(booking)
    notify(booking.workspace.owner, f"{name} signed the contract", url="/app/bookings/", icon="doc")
    return contract


def sign_contract_creative(contract, *, name, request=None):
    contract.creative_signature_name = name
    contract.signed_by_creative_at = timezone.now()
    contract.audit.append(_audit_entry("creative", name, request))
    contract.save()
    return contract


def _audit_entry(party, name, request):
    ip, ua = "", ""
    if request is not None:
        ip = request.META.get("REMOTE_ADDR", "")
        ua = request.META.get("HTTP_USER_AGENT", "")[:200]
    return {"party": party, "name": name, "ip": ip, "ua": ua,
            "at": timezone.now().isoformat()}


# ── Deposit / payments ─────────────────────────────────────────────────────
def _ensure_deposit_invoice(booking):
    inv = booking.invoices.filter(invoice_type=Invoice.Type.DEPOSIT).first()
    if not inv:
        inv = Invoice.objects.create(
            booking=booking, invoice_type=Invoice.Type.DEPOSIT,
            amount=booking.deposit_amount, due_date=timezone.now().date() + timedelta(days=7),
            status=Invoice.Status.SENT,
        )
    return inv


def pay_deposit(booking):
    # Don't take money for a date we can't honour (double-booking guard).
    if not availability.is_available(booking.workspace, booking.event_date, exclude_booking=booking):
        raise DateUnavailable(booking.event_date)
    invoice = _ensure_deposit_invoice(booking)
    if invoice.is_paid:
        return invoice.payments.first()
    payment = charge_invoice(invoice)
    # Only advance when the payment actually succeeded. The test gateway settles
    # synchronously; Stripe settles later via the webhook, which calls
    # settle_invoice() itself.
    if payment.status == Payment.Status.SUCCEEDED:
        settle_invoice(invoice)
    return payment


def settle_invoice(invoice):
    """Mark an invoice paid and advance the booking — the single place both the
    synchronous test gateway and the Stripe webhook funnel through. Idempotent."""
    if not invoice.is_paid:
        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=["status", "updated_at"])
    booking = invoice.booking
    if invoice.invoice_type == Invoice.Type.DEPOSIT and not booking.is_confirmed:
        booking.transition(Booking.Status.DEPOSIT_PAID)
        booking.transition(Booking.Status.CONFIRMED)
        _on_confirmed(booking)
    elif invoice.invoice_type == Invoice.Type.FINAL and booking.status != Booking.Status.COMPLETED:
        booking.transition(Booking.Status.FINAL_PAID)
        booking.transition(Booking.Status.COMPLETED)
        from apps.production.services import mark_all_done
        mark_all_done(booking)
        notify(booking.workspace.owner, f"Final payment received — {booking.title}", url="/app/bookings/", icon="card")
        notify(booking.client, "Thanks! Your booking is complete. Leave a review?", url=f"/portal/booking/{booking.id}/", icon="bell")


def _on_confirmed(booking):
    if booking.event_date:
        availability.mark_booked(booking.workspace, booking.event_date)
        CalendarEvent.objects.get_or_create(
            workspace=booking.workspace, booking=booking,
            event_type=CalendarEvent.Type.SHOOT,
            defaults={"title": booking.title,
                      "start": timezone.make_aware(
                          timezone.datetime.combine(booking.event_date, timezone.datetime.min.time().replace(hour=10)))},
        )
    # Generate the post-shoot delivery plan (back-up → edit → deliver…).
    from apps.production.services import generate_deliverables
    generate_deliverables(booking)
    notify(booking.client, "Booking confirmed — deposit received 🎉", url=f"/portal/booking/{booking.id}/", icon="card", email=True)
    notify(booking.workspace.owner, f"Deposit paid — {booking.title} confirmed", url="/app/bookings/", icon="card")


def pay_final(booking):
    inv = booking.invoices.filter(invoice_type=Invoice.Type.FINAL).first()
    if not inv:
        balance = booking.total - booking.deposit_amount
        inv = Invoice.objects.create(
            booking=booking, invoice_type=Invoice.Type.FINAL, amount=balance,
            due_date=timezone.now().date(), status=Invoice.Status.SENT,
        )
    if not inv.is_paid:
        payment = charge_invoice(inv)
        if payment.status == Payment.Status.SUCCEEDED:
            settle_invoice(inv)
    return inv


# ── Delivery / gallery ─────────────────────────────────────────────────────
def deliver_gallery(gallery):
    gallery.deliver()
    booking = gallery.booking
    if booking.status in {Booking.Status.SHOOT_COMPLETED, Booking.Status.EDITING, Booking.Status.CONFIRMED, Booking.Status.PLANNING}:
        booking.transition(Booking.Status.DELIVERED, force=True)
    from apps.production.services import mark_done
    mark_done(booking, "final_delivery")  # tick the delivery milestone
    notify(booking.client, f"Your gallery '{gallery.title}' is ready ✨", url=f"/portal/gallery/{gallery.id}/", icon="image", email=True)
    return gallery


# ── Cancellation ───────────────────────────────────────────────────────────
def cancel_booking(booking, *, by="creative", reason=""):
    """Cancel a booking, apply the refund policy, free its date and notify.

    A creative cancelling refunds everything paid (their fault); a client
    cancelling is subject to the sliding-scale policy (deposit non-refundable)."""
    from apps.payments.services import compute_refund

    breakdown = compute_refund(booking)
    if by == "creative":
        refund = breakdown["paid"]          # full refund when the creative cancels
    else:
        refund = breakdown["refundable"]    # policy applies to client cancellations

    booking.refunded_amount = refund
    new_status = Booking.Status.REFUNDED if refund > 0 else Booking.Status.CANCELLED
    booking.transition(new_status, force=True)
    booking.save(update_fields=["refunded_amount"])

    availability.free_date(booking.workspace, booking.event_date, exclude_booking=booking)
    booking.events.filter(event_type=CalendarEvent.Type.SHOOT).delete()

    note = f" Reason: {reason}" if reason else ""
    refund_note = f" A refund of ${refund:,.2f} will be processed." if refund > 0 else " No refund applies (deposit non-refundable)."
    if by == "creative":
        notify(booking.client, f"Your booking '{booking.title}' was cancelled by the creative.{refund_note}{note}",
               email=True, url=f"/portal/booking/{booking.id}/", icon="alert")
    else:
        notify(booking.workspace.owner, f"{booking.client.email} cancelled '{booking.title}'.{note}",
               url="/app/bookings/", icon="alert")
        if refund > 0:
            notify(booking.client, f"Your cancellation refund of ${refund:,.2f} is being processed.",
                   email=True, url=f"/portal/booking/{booking.id}/", icon="card")
    return booking


# ── Disputes ─────────────────────────────────────────────────────────────────
def raise_dispute(booking, *, user, role, reason, detail=""):
    from .models import Dispute

    dispute = Dispute.objects.create(
        booking=booking, raised_by=user, raised_by_role=role, reason=reason, detail=detail)
    other = booking.client if role == "creative" else booking.workspace.owner
    notify(other, f"A dispute was raised on '{booking.title}' — our team will review it.",
           email=True, url=(f"/app/bookings/{booking.id}/" if role == "client" else f"/portal/booking/{booking.id}/"),
           icon="alert")
    # Flag any platform admins so it enters the review queue.
    from django.contrib.auth import get_user_model
    for admin in get_user_model().objects.filter(is_staff=True)[:5]:
        notify(admin, f"New dispute ({dispute.get_reason_display()}) on {booking.title}",
               url="/admin/bookings/dispute/", icon="alert")
    return dispute


def resolve_dispute(dispute, *, resolved_by, status, resolution=""):
    from .models import Dispute

    dispute.status = status
    dispute.resolution = resolution
    dispute.resolved_by = resolved_by
    dispute.resolved_at = timezone.now()
    dispute.save()
    booking = dispute.booking
    verb = "resolved" if status == Dispute.Status.RESOLVED else "closed"
    for u in {booking.client, booking.workspace.owner}:
        notify(u, f"The dispute on '{booking.title}' was {verb}.", email=True,
               url="/portal/" if u == booking.client else "/app/bookings/", icon="bell")
    return dispute


# ── Review ─────────────────────────────────────────────────────────────────
def create_review(*, booking, rating, title="", body=""):
    review, _ = Review.objects.update_or_create(
        booking=booking,
        defaults={"client": booking.client, "workspace": booking.workspace,
                  "rating": rating, "title": title, "body": body, "verified": True},
    )
    notify(booking.workspace.owner, f"New {rating}★ review from {booking.client.email}", url="/app/", icon="bell")
    return review


DEFAULT_CONTRACT = """SERVICE AGREEMENT

This agreement is between {{business_name}} ("the Creative") and {{client_name}} ("the Client").

1. SERVICES. The Creative will provide photography/videography services for the event on {{event_date}} as described in the accepted quote.

2. FEES. The total fee is {{total}} (incl. GST). A non-refundable deposit of {{deposit}} is payable to confirm the booking. The balance is due on or before delivery.

3. CANCELLATION. Deposits are non-refundable. Cancellations within 14 days of the event may incur the full fee.

4. DELIVERY. Edited images/footage will be delivered via a private online gallery within the timeframe stated in the quote.

5. COPYRIGHT & USAGE. The Creative retains copyright. The Client receives a personal-use licence. Commercial usage, where applicable, is per the quote.

By signing below, both parties agree to these terms.
"""
